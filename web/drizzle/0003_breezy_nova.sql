CREATE TABLE `mesh_cache` (
	`id` text PRIMARY KEY NOT NULL,
	`label` text NOT NULL,
	`alternate_labels` text,
	`tree_numbers` text,
	`broader_terms` text,
	`narrower_terms` text,
	`scope_note` text,
	`fetched_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `mesh_lookup_index` (
	`id` text PRIMARY KEY NOT NULL,
	`search_term` text NOT NULL,
	`mesh_id` text,
	`match_type` text,
	FOREIGN KEY (`mesh_id`) REFERENCES `mesh_cache`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `mesh_lookup_search_term_idx` ON `mesh_lookup_index` (`search_term`);