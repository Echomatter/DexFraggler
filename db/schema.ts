import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const runs=sqliteTable('runs',{shape:text('shape').primaryKey(),state:text('state').notNull(),running:integer('running').notNull().default(0),revision:integer('revision').notNull().default(0),updatedAt:integer('updated_at').notNull(),leaseOwner:text('lease_owner'),leaseUntil:integer('lease_until').notNull().default(0),reference:text('reference')});
export const workers=sqliteTable('workers',{id:text('id').primaryKey(),lastSeen:integer('last_seen').notNull(),engine:text('engine').notNull()});
