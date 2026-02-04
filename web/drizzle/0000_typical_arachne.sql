CREATE TABLE `agent_states` (
	`id` text PRIMARY KEY NOT NULL,
	`research_id` text,
	`phase` text NOT NULL,
	`message` text,
	`overall_progress` integer DEFAULT 0,
	`planning_steps` text,
	`active_agents` text,
	`tool_executions` text,
	`state_file_path` text,
	`created_at` integer NOT NULL,
	`updated_at` integer,
	FOREIGN KEY (`research_id`) REFERENCES `research`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `api_keys` (
	`id` text PRIMARY KEY NOT NULL,
	`service` text NOT NULL,
	`api_key` text NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer
);
--> statement-breakpoint
CREATE TABLE `pcc_queries` (
	`id` text PRIMARY KEY NOT NULL,
	`research_id` text,
	`population` text,
	`concept` text,
	`context` text,
	`generated_query` text,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`research_id`) REFERENCES `research`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `pico_queries` (
	`id` text PRIMARY KEY NOT NULL,
	`research_id` text,
	`population` text,
	`intervention` text,
	`comparison` text,
	`outcome` text,
	`generated_pubmed_query` text,
	`mesh_terms` text,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`research_id`) REFERENCES `research`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `reports` (
	`id` text PRIMARY KEY NOT NULL,
	`research_id` text,
	`title` text,
	`content` text,
	`format` text DEFAULT 'markdown',
	`word_count` integer,
	`reference_count` integer,
	`version` integer DEFAULT 1,
	`created_at` integer NOT NULL,
	`updated_at` integer,
	FOREIGN KEY (`research_id`) REFERENCES `research`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `research` (
	`id` text PRIMARY KEY NOT NULL,
	`query` text NOT NULL,
	`query_type` text DEFAULT 'pico',
	`mode` text DEFAULT 'detailed',
	`status` text DEFAULT 'pending',
	`progress` integer DEFAULT 0,
	`title` text,
	`created_at` integer NOT NULL,
	`started_at` integer,
	`completed_at` integer,
	`duration_seconds` integer,
	`error_message` text
);
--> statement-breakpoint
CREATE TABLE `search_results` (
	`id` text PRIMARY KEY NOT NULL,
	`research_id` text,
	`title` text,
	`url` text,
	`snippet` text,
	`content` text,
	`source` text,
	`evidence_level` text,
	`publication_type` text,
	`mesh_terms` text,
	`doi` text,
	`pmid` text,
	`relevance_score` real,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`research_id`) REFERENCES `research`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `settings` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL,
	`category` text,
	`updated_at` integer
);
--> statement-breakpoint
CREATE INDEX `agent_states_research_id_idx` ON `agent_states` (`research_id`);--> statement-breakpoint
CREATE INDEX `agent_states_created_at_idx` ON `agent_states` (`created_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `api_keys_service_unique` ON `api_keys` (`service`);--> statement-breakpoint
CREATE INDEX `pcc_research_id_idx` ON `pcc_queries` (`research_id`);--> statement-breakpoint
CREATE INDEX `pico_research_id_idx` ON `pico_queries` (`research_id`);--> statement-breakpoint
CREATE INDEX `reports_research_id_idx` ON `reports` (`research_id`);--> statement-breakpoint
CREATE INDEX `research_status_idx` ON `research` (`status`);--> statement-breakpoint
CREATE INDEX `research_created_at_idx` ON `research` (`created_at`);--> statement-breakpoint
CREATE INDEX `search_results_research_id_idx` ON `search_results` (`research_id`);--> statement-breakpoint
CREATE INDEX `search_results_source_idx` ON `search_results` (`source`);