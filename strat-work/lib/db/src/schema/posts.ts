import { integer, pgTable, serial, text, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";
import { campaignsTable } from "./campaigns";

export const postsTable = pgTable("posts", {
  id: serial("id").primaryKey(),
  campaignId: integer("campaign_id").notNull().references(() => campaignsTable.id),
  channel: text("channel").notNull(),
  telegramUrl: text("telegram_url").notNull().default(""),
  content: text("content").notNull(),
  publishedAt: timestamp("published_at", { withTimezone: true }).notNull().defaultNow(),
  targetReactions: integer("target_reactions").notNull(),
  completedReactions: integer("completed_reactions").notNull().default(0),
  status: text("status").notNull().default("queued"),
  leaveStatus: text("leave_status").notNull().default("pending"),
});

export const insertPostSchema = createInsertSchema(postsTable).omit({ id: true });
export type InsertPost = z.infer<typeof insertPostSchema>;
export type Post = typeof postsTable.$inferSelect;