import { and, desc, eq, sql } from "drizzle-orm";
import { Router, type IRouter } from "express";
import {
  db,
  accountsTable,
  activityTable,
  campaignsTable,
  postsTable,
} from "@workspace/db";
import {
  CreateCampaignBody,
  CreateCampaignResponse,
  CreatePostBody,
  CreatePostResponse,
  GetDashboardSummaryResponse,
  GetPostParams,
  GetPostResponse,
  ListAccountsResponse,
  ListActivityResponse,
  ListCampaignsResponse,
  ListPostsQueryParams,
  ListPostsResponse,
  RetryPostParams,
  RetryPostResponse,
  UpdateCampaignBody,
  UpdateCampaignParams,
  UpdateCampaignResponse,
} from "@workspace/api-zod";

const router: IRouter = Router();

function dateOnly(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setUTCDate(result.getUTCDate() + days);
  return result;
}

function mapPost(
  post: typeof postsTable.$inferSelect,
  campaign: typeof campaignsTable.$inferSelect,
) {
  return {
    ...post,
    campaignName: campaign.name,
  };
}

async function seedDemoData(): Promise<void> {
  const [{ count }] = await db
    .select({ count: sql<number>`count(*)` })
    .from(campaignsTable);

  if (Number(count) > 0) return;

  const now = new Date();
  const [primaryCampaign, secondaryCampaign] = await db
    .insert(campaignsTable)
    .values([
      {
        name: "إطلاق الأسبوع",
        channel: "@daily_updates",
        durationDays: 10,
        reactionsPerPost: 10,
        status: "active",
        startDate: dateOnly(addDays(now, -4)),
        endDate: dateOnly(addDays(now, 6)),
      },
      {
        name: "حملة النشرة",
        channel: "@newsroom_ar",
        durationDays: 7,
        reactionsPerPost: 30,
        status: "active",
        startDate: dateOnly(addDays(now, -1)),
        endDate: dateOnly(addDays(now, 6)),
      },
    ])
    .returning();

  await db.insert(postsTable).values([
    {
      campaignId: primaryCampaign.id,
      channel: primaryCampaign.channel,
      content: "ملخص اليوم: أهم التحديثات التي تحتاج إلى معرفتها.",
      targetReactions: 10,
      completedReactions: 10,
      status: "completed",
      leaveStatus: "completed",
      publishedAt: addDays(now, -1),
    },
    {
      campaignId: primaryCampaign.id,
      channel: primaryCampaign.channel,
      content: "دليل عملي جديد مع خطوات واضحة وتفاصيل قابلة للتطبيق.",
      targetReactions: 10,
      completedReactions: 7,
      status: "processing",
      leaveStatus: "in_progress",
      publishedAt: new Date(now.getTime() - 1000 * 60 * 90),
    },
    {
      campaignId: secondaryCampaign.id,
      channel: secondaryCampaign.channel,
      content: "خبر عاجل: نتابع التفاصيل وننشر المستجدات أولًا بأول.",
      targetReactions: 30,
      completedReactions: 0,
      status: "queued",
      leaveStatus: "pending",
      publishedAt: new Date(now.getTime() - 1000 * 60 * 20),
    },
    {
      campaignId: primaryCampaign.id,
      channel: primaryCampaign.channel,
      content: "نتائج الأسبوع والأرقام التي صنعت الفرق.",
      targetReactions: 10,
      completedReactions: 10,
      status: "completed",
      leaveStatus: "completed",
      publishedAt: addDays(now, -2),
    },
  ]);

  await db.insert(accountsTable).values([
    { handle: "@pulse_01", status: "available", totalReactions: 184, lastAction: "متاح الآن" },
    { handle: "@pulse_02", status: "reacting", totalReactions: 169, lastAction: "يتفاعل مع بوست #1042" },
    { handle: "@pulse_03", status: "leaving", totalReactions: 152, lastAction: "يغادر بعد التفاعل" },
    { handle: "@pulse_04", status: "cooldown", totalReactions: 141, lastAction: "يعود خلال 12 دقيقة" },
    { handle: "@pulse_05", status: "available", totalReactions: 128, lastAction: "متاح الآن" },
    { handle: "@pulse_06", status: "available", totalReactions: 121, lastAction: "متاح الآن" },
  ]);

  await db.insert(activityTable).values([
    { type: "reaction", message: "اكتمل تفاعل 10 حسابات مع بوست #1041", tone: "success", createdAt: new Date(now.getTime() - 1000 * 60 * 4) },
    { type: "leave", message: "غادرت 10 حسابات بعد إتمام التفاعل", tone: "neutral", createdAt: new Date(now.getTime() - 1000 * 60 * 8) },
    { type: "post", message: "تمت إضافة بوست جديد إلى حملة إطلاق الأسبوع", tone: "neutral", createdAt: new Date(now.getTime() - 1000 * 60 * 18) },
    { type: "warning", message: "حساب واحد دخل فترة التهدئة", tone: "warning", createdAt: new Date(now.getTime() - 1000 * 60 * 26) },
  ]);
}

router.get("/dashboard-summary", async (_req, res): Promise<void> => {
  await seedDemoData();
  const [campaignStats] = await db
    .select({ count: sql<number>`count(*)` })
    .from(campaignsTable)
    .where(eq(campaignsTable.status, "active"));
  const [postStats] = await db
    .select({
      total: sql<number>`count(*)`,
      completed: sql<number>`count(*) filter (where ${postsTable.status} = 'completed')`,
      reactions: sql<number>`coalesce(sum(${postsTable.completedReactions}), 0)`,
    })
    .from(postsTable);
  const [accountStats] = await db
    .select({ count: sql<number>`count(*)` })
    .from(accountsTable)
    .where(eq(accountsTable.status, "available"));

  res.json(
    GetDashboardSummaryResponse.parse({
      activeCampaigns: Number(campaignStats.count),
      totalPosts: Number(postStats.total),
      completedPosts: Number(postStats.completed),
      reactionsToday: Number(postStats.reactions),
      availableAccounts: Number(accountStats.count),
      queueHealth: Number(postStats.total) === 0 ? 100 : Math.round((Number(postStats.completed) / Number(postStats.total)) * 1000) / 10,
    }),
  );
});

router.get("/campaigns", async (_req, res): Promise<void> => {
  await seedDemoData();
  const campaigns = await db.select().from(campaignsTable).orderBy(desc(campaignsTable.createdAt));
  const posts = await db.select().from(postsTable);
  const response = campaigns.map((campaign) => {
    const relatedPosts = posts.filter((post) => post.campaignId === campaign.id);
    return {
      ...campaign,
      postsCount: relatedPosts.length,
      totalReactions: relatedPosts.reduce((sum, post) => sum + post.targetReactions, 0),
      completedReactions: relatedPosts.reduce((sum, post) => sum + post.completedReactions, 0),
    };
  });
  res.json(ListCampaignsResponse.parse(response));
});

router.post("/campaigns", async (req, res): Promise<void> => {
  const parsed = CreateCampaignBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  const now = new Date();
  const [campaign] = await db
    .insert(campaignsTable)
    .values({
      ...parsed.data,
      status: "active",
      startDate: dateOnly(now),
      endDate: dateOnly(addDays(now, parsed.data.durationDays)),
    })
    .returning();
  res.status(201).json(
    CreateCampaignResponse.parse({
      ...campaign,
      postsCount: 0,
      totalReactions: 0,
      completedReactions: 0,
    }),
  );
});

router.patch("/campaigns/:id", async (req, res): Promise<void> => {
  const params = UpdateCampaignParams.safeParse(req.params);
  const body = UpdateCampaignBody.safeParse(req.body);
  if (!params.success || !body.success) {
    res.status(400).json({ error: "بيانات الحملة غير صالحة" });
    return;
  }
  const [campaign] = await db
    .update(campaignsTable)
    .set({ status: body.data.status })
    .where(eq(campaignsTable.id, params.data.id))
    .returning();
  if (!campaign) {
    res.status(404).json({ error: "Campaign not found" });
    return;
  }
  const posts = await db.select().from(postsTable).where(eq(postsTable.campaignId, campaign.id));
  res.json(
    UpdateCampaignResponse.parse({
      ...campaign,
      postsCount: posts.length,
      totalReactions: posts.reduce((sum, post) => sum + post.targetReactions, 0),
      completedReactions: posts.reduce((sum, post) => sum + post.completedReactions, 0),
    }),
  );
});

router.get("/posts", async (req, res): Promise<void> => {
  await seedDemoData();
  const query = ListPostsQueryParams.safeParse(req.query);
  if (!query.success) {
    res.status(400).json({ error: query.error.message });
    return;
  }
  const [posts, campaigns] = await Promise.all([
    query.data.status === "all"
      ? db.select().from(postsTable).orderBy(desc(postsTable.publishedAt))
      : db.select().from(postsTable).where(eq(postsTable.status, query.data.status)).orderBy(desc(postsTable.publishedAt)),
    db.select().from(campaignsTable),
  ]);
  const campaignsById = new Map(campaigns.map((campaign) => [campaign.id, campaign]));
  const response = posts
    .map((post) => {
      const campaign = campaignsById.get(post.campaignId);
      return campaign ? mapPost(post, campaign) : null;
    })
    .filter((post): post is NonNullable<typeof post> => post !== null);
  res.json(ListPostsResponse.parse(response));
});

router.post("/posts", async (req, res): Promise<void> => {
  const parsed = CreatePostBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  const [campaign] = await db.select().from(campaignsTable).where(eq(campaignsTable.id, parsed.data.campaignId));
  if (!campaign) {
    res.status(404).json({ error: "Campaign not found" });
    return;
  }
  const [post] = await db
    .insert(postsTable)
    .values({
      ...parsed.data,
      status: "queued",
      leaveStatus: "pending",
      completedReactions: 0,
    })
    .returning();
  await db.insert(activityTable).values({
    type: "post",
    message: `تمت إضافة بوست جديد إلى ${campaign.name}`,
    tone: "neutral",
  });
  res.status(201).json(CreatePostResponse.parse(mapPost(post, campaign)));
});

router.get("/posts/:id", async (req, res): Promise<void> => {
  const params = GetPostParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const [post] = await db.select().from(postsTable).where(eq(postsTable.id, params.data.id));
  if (!post) {
    res.status(404).json({ error: "Post not found" });
    return;
  }
  const [campaign] = await db.select().from(campaignsTable).where(eq(campaignsTable.id, post.campaignId));
  if (!campaign) {
    res.status(404).json({ error: "Campaign not found" });
    return;
  }
  res.json(GetPostResponse.parse(mapPost(post, campaign)));
});

router.post("/posts/:id", async (req, res): Promise<void> => {
  const params = RetryPostParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const [post] = await db
    .update(postsTable)
    .set({ status: "queued", leaveStatus: "pending" })
    .where(eq(postsTable.id, params.data.id))
    .returning();
  if (!post) {
    res.status(404).json({ error: "Post not found" });
    return;
  }
  const [campaign] = await db.select().from(campaignsTable).where(eq(campaignsTable.id, post.campaignId));
  if (!campaign) {
    res.status(404).json({ error: "Campaign not found" });
    return;
  }
  await db.insert(activityTable).values({
    type: "retry",
    message: `تمت إعادة بوست #${post.id} إلى الطابور`,
    tone: "warning",
  });
  res.json(RetryPostResponse.parse(mapPost(post, campaign)));
});

router.get("/accounts", async (_req, res): Promise<void> => {
  await seedDemoData();
  const accounts = await db.select().from(accountsTable).orderBy(desc(accountsTable.totalReactions));
  res.json(ListAccountsResponse.parse(accounts));
});

router.get("/activity", async (_req, res): Promise<void> => {
  await seedDemoData();
  const activity = await db.select().from(activityTable).orderBy(desc(activityTable.createdAt)).limit(20);
  res.json(ListActivityResponse.parse(activity));
});

export default router;