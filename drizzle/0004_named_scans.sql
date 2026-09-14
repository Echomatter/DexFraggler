CREATE TABLE `scan_seeds` (
	`scan_id` text NOT NULL,
	`key` text NOT NULL,
	`cell_id` integer NOT NULL,
	`patch` text NOT NULL,
	PRIMARY KEY(`scan_id`, `key`)
);
--> statement-breakpoint
CREATE TABLE `scans` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`config` text NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_map_cells` (
	`scan_id` text DEFAULT 'initial' NOT NULL,
	`id` integer NOT NULL,
	`patch` text NOT NULL,
	`state` text,
	`reference` text,
	`target_key` text DEFAULT '' NOT NULL,
	`visits` integer DEFAULT 0 NOT NULL,
	`evaluations` integer DEFAULT 0 NOT NULL,
	`model_score` text,
	`native_score` text,
	`native_loss` text,
	`updated_at` integer DEFAULT 0 NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`failed_until` integer DEFAULT 0 NOT NULL,
	`last_error` text,
	PRIMARY KEY(`scan_id`, `id`)
);
--> statement-breakpoint
INSERT INTO `__new_map_cells`("scan_id", "id", "patch", "state", "reference", "target_key", "visits", "evaluations", "model_score", "native_score", "native_loss", "updated_at", "revision", "failed_until", "last_error") SELECT 'initial', "id", "patch", "state", "reference", "target_key", "visits", "evaluations", "model_score", "native_score", "native_loss", "updated_at", "revision", "failed_until", "last_error" FROM `map_cells`;--> statement-breakpoint
DROP TABLE `map_cells`;--> statement-breakpoint
ALTER TABLE `__new_map_cells` RENAME TO `map_cells`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
ALTER TABLE `map_board` ADD `scan_id` text DEFAULT 'initial' NOT NULL;