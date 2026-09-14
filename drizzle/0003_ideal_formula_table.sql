DELETE FROM `map_cells`;--> statement-breakpoint
DELETE FROM `workers`;--> statement-breakpoint
UPDATE `map_board` SET
 config=json_object('allowDetune',json(CASE WHEN json_extract(config,'$.allowDetune')=1 THEN 'true' ELSE 'false' END),'anchors',json(COALESCE((SELECT CASE WHEN count(*)>0 THEN json_group_array(json_object('slot',slot,'shape',shape)) END FROM (SELECT json_extract(value,'$.slot') AS slot,json_extract(value,'$.shape') AS shape FROM json_each(map_board.config,'$.anchors') WHERE json_extract(value,'$.shape') IN ('sine','triangle','square','saw') ORDER BY slot)), '[{"slot":0,"shape":"triangle"},{"slot":15,"shape":"square"},{"slot":31,"shape":"saw"}]'))),
 generation=generation+1,revision=revision+1,running=0,lease_owner=NULL,lease_until=0,active_id=NULL;
--> statement-breakpoint
DROP TABLE `runs`;--> statement-breakpoint
ALTER TABLE `map_cells` DROP COLUMN `seeds`;--> statement-breakpoint
ALTER TABLE `map_cells` DROP COLUMN `provenance`;
