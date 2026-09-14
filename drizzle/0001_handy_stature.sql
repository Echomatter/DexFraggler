CREATE TABLE `map_board` (
	`id` integer PRIMARY KEY NOT NULL,
	`config` text NOT NULL,
	`running` integer DEFAULT 0 NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`generation` integer DEFAULT 0 NOT NULL,
	`lease_owner` text,
	`lease_until` integer DEFAULT 0 NOT NULL,
	`active_id` integer
);
--> statement-breakpoint
CREATE TABLE `map_cells` (
	`id` integer PRIMARY KEY NOT NULL,
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
	`seeds` text DEFAULT '[]' NOT NULL,
	`provenance` text
);
