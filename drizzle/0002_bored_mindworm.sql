ALTER TABLE `map_cells` ADD `failed_until` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `map_cells` ADD `last_error` text;