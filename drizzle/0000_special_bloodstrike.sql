CREATE TABLE `runs` (
	`shape` text PRIMARY KEY NOT NULL,
	`state` text NOT NULL,
	`running` integer DEFAULT 0 NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`updated_at` integer NOT NULL,
	`lease_owner` text,
	`lease_until` integer DEFAULT 0 NOT NULL,
	`reference` text
);
--> statement-breakpoint
CREATE TABLE `workers` (
	`id` text PRIMARY KEY NOT NULL,
	`last_seen` integer NOT NULL,
	`engine` text NOT NULL
);
