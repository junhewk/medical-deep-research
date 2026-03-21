mod server;

use server::{ServerState, start_server, stop_server};
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ServerState::default())
        .setup(|app| {
            let handle = app.handle().clone();

            // Start the Next.js server in background
            tauri::async_runtime::spawn(async move {
                match start_server(&handle).await {
                    Ok(url) => {
                        log::info!("Navigating to {url}");
                        if let Some(window) = handle.get_webview_window("main") {
                            let _ = window.navigate(url.parse().unwrap());
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    Err(e) => {
                        log::error!("Failed to start server: {e}");
                        // Show error in the main window
                        if let Some(window) = handle.get_webview_window("main") {
                            let error_html = format!(
                                "data:text/html,<html><body style='background:#0f172a;color:#f87171;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center;max-width:500px'><h2>Failed to Start</h2><p style='color:#94a3b8'>{}</p></div></body></html>",
                                e.replace('\'', "&#39;").replace('"', "&quot;")
                            );
                            let _ = window.navigate(error_html.parse().expect("error HTML data URL must be valid"));
                            let _ = window.show();
                        }
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                stop_server(app);
            }
        });
}
