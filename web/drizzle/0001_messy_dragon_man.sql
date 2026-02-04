CREATE TABLE `llm_config` (
	`id` text PRIMARY KEY NOT NULL,
	`provider` text NOT NULL,
	`model` text NOT NULL,
	`is_default` integer DEFAULT false,
	`created_at` integer NOT NULL,
	`updated_at` integer
);
--> statement-breakpoint
ALTER TABLE `search_results` ADD `authors` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `journal` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `volume` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `issue` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `pages` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `publication_year` text;--> statement-breakpoint
ALTER TABLE `search_results` ADD `citation_count` integer;--> statement-breakpoint
ALTER TABLE `search_results` ADD `composite_score` real;--> statement-breakpoint
ALTER TABLE `search_results` ADD `evidence_level_score` real;--> statement-breakpoint
ALTER TABLE `search_results` ADD `citation_score` real;--> statement-breakpoint
ALTER TABLE `search_results` ADD `recency_score` real;--> statement-breakpoint
ALTER TABLE `search_results` ADD `reference_number` integer;--> statement-breakpoint
ALTER TABLE `search_results` ADD `vancouver_citation` text;--> statement-breakpoint
CREATE INDEX `search_results_composite_score_idx` ON `search_results` (`composite_score`);