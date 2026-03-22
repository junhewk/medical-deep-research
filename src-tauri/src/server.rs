use std::sync::Mutex;
use std::time::Duration;
use rand::Rng;
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

pub struct ServerState {
    pub child: Mutex<Option<CommandChild>>,
}

impl Default for ServerState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }
}

pub async fn start_server(app: &AppHandle) -> Result<(String, String), String> {
    // 1. Find available port and generate auth token
    let port = portpicker::pick_unused_port().ok_or("No available port found")?;
    let auth_token: String = {
        let mut rng = rand::thread_rng();
        (0..32).map(|_| format!("{:02x}", rng.gen::<u8>())).collect()
    };

    // 2. Resolve data paths
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to get app data dir: {e}"))?;

    let data_dir = app_data_dir.join("data");
    let db_path = data_dir.join("medical-deep-research.db");
    let research_dir = data_dir.join("research");

    // Ensure directories exist
    std::fs::create_dir_all(&research_dir)
        .map_err(|e| format!("Failed to create data directories: {e}"))?;

    log::info!("Data directory: {}", data_dir.display());
    log::info!("Database path: {}", db_path.display());

    // 3. Run DB init script (idempotent — safe to run every startup)
    let init_script = app
        .path()
        .resolve("resources/init-db.ts", BaseDirectory::Resource)
        .map_err(|e| format!("Failed to resolve init-db.ts: {e}"))?;

    if init_script.exists() {
        log::info!("Running database initialization...");
        let shell = app.shell();
        let output = shell
            .sidecar("bun")
            .map_err(|e| format!("Failed to create bun sidecar for init: {e}"))?
            .args(["run", &init_script.to_string_lossy()])
            .env("DATABASE_PATH", db_path.to_string_lossy().to_string())
            .env("DATA_DIR", data_dir.to_string_lossy().to_string())
            .output()
            .await
            .map_err(|e| format!("Failed to run init-db.ts: {e}"))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            log::error!("DB init stderr: {stderr}");
            return Err(format!("Database initialization failed: {stderr}"));
        }
        log::info!("Database initialized successfully");
    } else {
        log::warn!("init-db.ts not found at {}, skipping DB init", init_script.display());
    }

    // 4. Resolve standalone server path
    let standalone_dir = app
        .path()
        .resolve("resources/standalone", BaseDirectory::Resource)
        .map_err(|e| format!("Failed to resolve standalone dir: {e}"))?;

    let server_js = standalone_dir.join("server.js");
    if !server_js.exists() {
        return Err(format!("server.js not found at {}", server_js.display()));
    }

    // 5. Spawn Bun sidecar running the Next.js standalone server
    log::info!("Starting Next.js server on port {port}...");
    let shell = app.shell();
    let (mut rx, child) = shell
        .sidecar("bun")
        .map_err(|e| format!("Failed to create bun sidecar: {e}"))?
        .args(["run", &server_js.to_string_lossy()])
        .env("PORT", port.to_string())
        .env("HOSTNAME", "127.0.0.1")
        .env("NODE_ENV", "production")
        .env("INTERNAL_AUTH_TOKEN", &auth_token)
        .env("DATABASE_PATH", db_path.to_string_lossy().to_string())
        .env("DATA_DIR", data_dir.to_string_lossy().to_string())
        .current_dir(standalone_dir)
        .spawn()
        .map_err(|e| format!("Failed to spawn server: {e}"))?;

    // Log server output in background
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("[next] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    log::error!("[next] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("Server process terminated: {:?}", payload);
                    // Could emit event to frontend for error display
                    let _ = app_handle.emit("server-terminated", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    // 6. Store child process in state for later cleanup
    let server_url = format!("http://127.0.0.1:{port}");

    let state = app.state::<ServerState>();
    *state.child.lock().unwrap() = Some(child);

    // 7. Wait for server to be ready
    wait_for_server(&server_url, &auth_token, Duration::from_secs(30)).await?;

    log::info!("Server ready at {server_url}");
    Ok((server_url, auth_token))
}

async fn wait_for_server(url: &str, token: &str, timeout: Duration) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let start = std::time::Instant::now();
    loop {
        if start.elapsed() > timeout {
            return Err(format!(
                "Server did not become ready within {}s",
                timeout.as_secs()
            ));
        }

        match client.get(url).header("x-internal-token", token).send().await {
            Ok(resp) if resp.status().is_success() || resp.status().is_redirection() => {
                return Ok(());
            }
            _ => {
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
        }
    }
}

pub fn stop_server(app: &AppHandle) {
    let state = app.state::<ServerState>();
    let mut guard = state.child.lock().unwrap();
    if let Some(child) = guard.take() {
        log::info!("Stopping server...");
        let _ = child.kill();
    }
}
