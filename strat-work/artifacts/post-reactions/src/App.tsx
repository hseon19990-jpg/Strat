import { type FormEvent, type ReactNode, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import {
  Activity as ActivityIcon,
  AlertCircle,
  ArrowLeft,
  ArrowUpLeft,
  BarChart3,
  Check,
  ChevronLeft,
  CircleHelp,
  Command,
  ExternalLink,
  Filter,
  Inbox,
  Layers3,
  LoaderCircle,
  Menu,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ServerCog,
  Settings2,
  ShieldCheck,
  UsersRound,
  X,
  Zap,
} from 'lucide-react';
import {
  getGetDashboardSummaryQueryKey,
  getGetPostQueryKey,
  getListCampaignsQueryKey,
  getListPostsQueryKey,
  useCreateCampaign,
  useCreatePost,
  useGetDashboardSummary,
  useGetPost,
  useListAccounts,
  useListActivity,
  useListCampaigns,
  useListPosts,
  useRetryPost,
  useUpdateCampaign,
} from '@workspace/api-client-react';
import type { Account, Activity, Campaign, Post } from '@workspace/api-client-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Route, Switch, Link, useLocation, Router as WouterRouter } from 'wouter';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient();

const navItems = [
  { href: '/', label: 'نظرة عامة', english: 'Overview', icon: BarChart3 },
  { href: '/campaigns', label: 'الحملات', english: 'Campaigns', icon: Layers3 },
  { href: '/posts', label: 'طابور المنشورات', english: 'Post queue', icon: Inbox },
  { href: '/accounts', label: 'الحسابات', english: 'Accounts', icon: UsersRound },
];

const number = (value: number | undefined) => new Intl.NumberFormat('en-US').format(value ?? 0);
const date = (value: string | undefined) =>
  value ? new Intl.DateTimeFormat('ar-SA', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value)) : '—';
const timeAgo = (value: string | undefined) => {
  if (!value) return '—';
  const minutes = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 60) return `منذ ${minutes} د`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `منذ ${hours} س`;
  return `منذ ${Math.round(hours / 24)} يوم`;
};

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(' ');
}

function StatusDot({ tone = 'teal' }: { tone?: 'teal' | 'amber' | 'red' | 'blue' | 'slate' }) {
  const tones = { teal: 'bg-primary', amber: 'bg-accent', red: 'bg-destructive', blue: 'bg-sky-500', slate: 'bg-muted-foreground' };
  return <span className={cn('inline-block h-2 w-2 rounded-full', tones[tone], tone === 'teal' && 'status-pulse')} aria-hidden="true" />;
}

function StatusBadge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'teal' | 'amber' | 'red' | 'blue' | 'slate' }) {
  const styles = {
    teal: 'border-primary/20 bg-primary/10 text-primary',
    amber: 'border-accent/30 bg-accent/15 text-amber-800',
    red: 'border-destructive/20 bg-destructive/10 text-destructive',
    blue: 'border-sky-500/20 bg-sky-500/10 text-sky-700',
    slate: 'border-border bg-muted text-muted-foreground',
  };
  return <span className={cn('inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold', styles[tone])}><StatusDot tone={tone} />{children}</span>;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    active: 'نشطة', paused: 'متوقفة', expired: 'منتهية', queued: 'في الانتظار', processing: 'قيد التنفيذ',
    completed: 'مكتمل', failed: 'تحتاج إعادة', pending: 'بانتظار المغادرة', in_progress: 'المغادرة قيد التنفيذ',
    available: 'متاح', reacting: 'يتفاعل', leaving: 'يغادر بعد التفاعل', cooldown: 'فترة تهدئة',
  };
  return labels[status] ?? status;
}

function statusTone(status: string): 'teal' | 'amber' | 'red' | 'blue' | 'slate' {
  if (['active', 'completed', 'available'].includes(status)) return 'teal';
  if (['paused', 'queued', 'pending', 'cooldown'].includes(status)) return 'amber';
  if (['failed'].includes(status)) return 'red';
  if (['processing', 'reacting', 'in_progress'].includes(status)) return 'blue';
  return 'slate';
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-lg bg-muted', className)} />;
}

function QueryState({ loading, error, empty, children, retry }: { loading: boolean; error: boolean; empty?: boolean; children: ReactNode; retry?: () => void }) {
  if (loading) return <div className="space-y-3"><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div>;
  if (error) return <div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border border-destructive/20 bg-destructive/5 p-6 text-center"><AlertCircle className="h-6 w-6 text-destructive" /><p className="text-sm font-semibold">تعذر تحميل البيانات</p><p className="text-xs text-muted-foreground">تحقق من اتصال الخدمة ثم حاول مجدداً.</p>{retry && <button data-testid="button-retry-query" onClick={retry} className="rounded-lg bg-card px-3 py-2 text-xs font-bold text-foreground shadow-sm hover:bg-muted">إعادة المحاولة</button>}</div>;
  if (empty) return <div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card/60 p-6 text-center"><Inbox className="h-7 w-7 text-muted-foreground" /><p className="text-sm font-semibold">لا توجد بيانات هنا بعد</p><p className="max-w-sm text-xs leading-5 text-muted-foreground">ستظهر العناصر الجديدة هنا فور تسجيلها في النظام.</p></div>;
  return children;
}

function Modal({ title, eyebrow, onClose, children }: { title: string; eyebrow?: string; onClose: () => void; children: ReactNode }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[hsl(197_39%_13%/0.52)] p-4 backdrop-blur-sm">
    <div className="page-enter max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-2xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div><p className="mb-1 text-[10px] font-bold uppercase tracking-[0.18em] text-primary">{eyebrow ?? 'Control room'}</p><h2 className="text-xl font-bold tracking-tight">{title}</h2></div>
        <button data-testid="button-close-modal" onClick={onClose} className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"><X className="h-4 w-4" /></button>
      </div>
      {children}
    </div>
  </div>;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="block space-y-2"><span className="flex items-center justify-between text-xs font-bold text-foreground"><span>{label}</span>{hint && <span className="font-normal text-muted-foreground">{hint}</span>}</span>{children}</label>;
}

function Shell({ children }: { children: ReactNode }) {
  const [location, setLocation] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const active = navItems.find((item) => item.href === location)?.href ?? '/';
  return <div dir="rtl" className="min-h-[100dvh] bg-background text-foreground">
    <aside className={cn('fixed inset-y-0 right-0 z-40 flex w-72 flex-col border-l border-sidebar-border bg-sidebar px-4 py-5 text-sidebar-foreground transition-transform duration-300 lg:translate-x-0', mobileOpen ? 'translate-x-0' : 'translate-x-full')}>
      <div className="mb-9 flex items-center justify-between px-3">
        <Link href="/" data-testid="link-brand" className="flex items-center gap-3" onClick={() => setMobileOpen(false)}>
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground shadow-lg shadow-sidebar-primary/15"><Command className="h-5 w-5" /></span>
          <span><strong className="block text-sm tracking-tight text-sidebar-accent-foreground">رِدّة</strong><span className="font-mono text-[9px] uppercase tracking-[0.2em] text-sidebar-foreground/60">reaction ops</span></span>
        </Link>
        <button data-testid="button-close-sidebar" onClick={() => setMobileOpen(false)} className="rounded-lg p-2 text-sidebar-foreground/70 hover:bg-sidebar-accent lg:hidden"><X className="h-4 w-4" /></button>
      </div>
      <div className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[0.2em] text-sidebar-foreground/45">مساحة التشغيل / workspace</div>
      <nav className="space-y-1">
        {navItems.map((item) => { const Icon = item.icon; const isActive = active === item.href; return <Link key={item.href} href={item.href} data-testid={`link-nav-${item.english.toLowerCase().replace(' ', '-')}`} onClick={() => setMobileOpen(false)} className={cn('group flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors', isActive ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-inner' : 'text-sidebar-foreground/68 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground')}><Icon className={cn('h-4 w-4', isActive ? 'text-sidebar-primary' : 'text-sidebar-foreground/50')} /><span className="flex-1">{item.label}</span><span className="font-mono text-[9px] opacity-45">{item.english}</span></Link>; })}
      </nav>
      <div className="mt-auto space-y-3">
        <div className="rounded-2xl border border-sidebar-border bg-sidebar-accent/50 p-4">
          <div className="mb-3 flex items-center justify-between"><span className="text-xs font-semibold">حالة الخدمة</span><StatusDot tone="teal" /></div>
          <div className="mb-2 flex items-end justify-between"><span className="font-mono text-2xl font-semibold text-sidebar-primary">مستقر</span><span className="text-[10px] text-sidebar-foreground/55">آخر 24 ساعة</span></div>
          <div className="grid grid-cols-12 gap-1"><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /><span className="h-1.5 rounded-full bg-sidebar-primary" /></div>
        </div>
        <button data-testid="button-settings" onClick={() => setLocation('/')} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"><Settings2 className="h-4 w-4" />الإعدادات التشغيلية</button>
      </div>
    </aside>
    <div className="lg:mr-72">
      <header className="sticky top-0 z-30 flex h-[76px] items-center justify-between border-b border-border/80 bg-background/90 px-4 backdrop-blur-xl sm:px-8">
        <div className="flex items-center gap-3"><button data-testid="button-open-sidebar" onClick={() => setMobileOpen(true)} className="rounded-lg p-2 hover:bg-muted lg:hidden"><Menu className="h-5 w-5" /></button><div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">OPS / LIVE QUEUE</p><h1 className="mt-0.5 text-sm font-semibold">{active === '/' ? 'مركز المراقبة' : navItems.find((item) => item.href === active)?.label}</h1></div></div>
        <div className="flex items-center gap-3"><div className="hidden items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-3 py-1.5 text-[11px] font-semibold text-primary sm:flex"><StatusDot />النظام يعمل بشكل طبيعي</div><button data-testid="button-help" className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"><CircleHelp className="h-4 w-4" /></button><span className="grid h-9 w-9 place-items-center rounded-full bg-secondary font-bold text-secondary-foreground">م</span></div>
      </header>
      <main className="control-grid min-h-[calc(100dvh-76px)] bg-background/80 px-4 py-7 sm:px-8 sm:py-9"><div className="mx-auto max-w-[1500px]">{children}</div></main>
    </div>
  </div>;
}

function PageIntro({ label, title, description, action }: { label: string; title: string; description: string; action?: ReactNode }) {
  return <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-[0.22em] text-primary">{label}</p><h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p></div>{action}</div>;
}

function MetricCard({ label, value, sub, icon: Icon, accent = 'teal' }: { label: string; value: string | number; sub: string; icon: typeof BarChart3; accent?: 'teal' | 'amber' | 'blue' }) {
  return <div className="group rounded-2xl border border-border bg-card p-5 shadow-[0_8px_24px_hsl(197_35%_20%/0.04)] transition-transform hover:-translate-y-0.5"><div className="mb-5 flex items-start justify-between"><span className={cn('grid h-9 w-9 place-items-center rounded-xl', accent === 'teal' ? 'bg-primary/10 text-primary' : accent === 'amber' ? 'bg-accent/20 text-amber-700' : 'bg-sky-500/10 text-sky-700')}><Icon className="h-4 w-4" /></span><ArrowUpLeft className="h-4 w-4 text-muted-foreground/40" /></div><div className="font-mono text-3xl font-semibold tracking-tight">{value}</div><div className="mt-1 text-xs font-bold text-foreground">{label}</div><div className="mt-2 text-[11px] text-muted-foreground">{sub}</div></div>;
}

function Overview() {
  const summary = useGetDashboardSummary();
  const activity = useListActivity();
  const campaigns = useListCampaigns();
  const posts = useListPosts({ status: 'all' });
  const [selectedPost, setSelectedPost] = useState<number | null>(null);
  const retry = useRetryPost();
  const qc = useQueryClient();
  const selected = useGetPost(selectedPost ?? 0, { query: { enabled: !!selectedPost, queryKey: getGetPostQueryKey(selectedPost ?? 0) } });
  const latestPosts = (posts.data ?? []).slice(0, 5);
  const activeCampaign = (campaigns.data ?? []).find((campaign) => campaign.status === 'active');
  const refresh = () => { summary.refetch(); activity.refetch(); campaigns.refetch(); posts.refetch(); };
  return <div className="page-enter">
    <PageIntro label="نظام التشغيل / overview" title="صباح الخير، فريق التشغيل" description="نظرة واحدة على تدفق التفاعلات، صحة الطابور، وتوفر الحسابات. القاعدة ثابتة: كل منشور مؤهل يتلقى العدد المستهدف مرة واحدة فقط." action={<button data-testid="button-refresh-overview" onClick={refresh} className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-xs font-bold shadow-sm hover:bg-muted"><RefreshCw className={cn('h-4 w-4', summary.isFetching && 'animate-spin')} />تحديث البيانات</button>} />
    <QueryState loading={summary.isLoading} error={!!summary.error} retry={refresh}><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><MetricCard label="الحملات النشطة" value={number(summary.data?.activeCampaigns)} sub="تعمل الآن" icon={Zap} /><MetricCard label="إجمالي المنشورات" value={number(summary.data?.totalPosts)} sub="ضمن كل الحملات" icon={Inbox} accent="blue" /><MetricCard label="منشورات مكتملة" value={number(summary.data?.completedPosts)} sub={`${summary.data?.totalPosts ? Math.round((summary.data.completedPosts / summary.data.totalPosts) * 100) : 0}% من الإجمالي`} icon={Check} /><MetricCard label="التفاعلات المنفذة" value={number(summary.data?.reactionsToday)} sub="مرة واحدة لكل بوست" icon={ActivityIcon} accent="amber" /><MetricCard label="حسابات متاحة" value={number(summary.data?.availableAccounts)} sub="جاهزة للتوزيع" icon={UsersRound} accent="blue" /></div></QueryState>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.45fr_.8fr]">
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6"><div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">QUEUE HEALTH</p><h3 className="mt-1 text-base font-bold">صحة الطابور</h3></div><span className="font-mono text-sm font-semibold text-primary">{summary.data?.queueHealth ?? 0}%</span></div><div className="relative h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${summary.data?.queueHealth ?? 0}%` }} /></div><div className="mt-4 grid grid-cols-3 gap-3 text-center text-[11px]"><div><span className="mb-1 block font-mono text-lg font-semibold">{number(summary.data?.totalPosts ? summary.data.totalPosts - (summary.data.completedPosts ?? 0) : 0)}</span><span className="text-muted-foreground">قيد المعالجة</span></div><div className="border-x border-border"><span className="mb-1 block font-mono text-lg font-semibold">{number(summary.data?.completedPosts)}</span><span className="text-muted-foreground">منشور مكتمل</span></div><div><span className="mb-1 block font-mono text-lg font-semibold text-primary">{number(summary.data?.availableAccounts)}</span><span className="text-muted-foreground">حساب متاح</span></div></div><div className="mt-6 rounded-xl border border-primary/15 bg-primary/5 p-4"><div className="flex gap-3"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p className="text-xs leading-5 text-foreground/75">يُضمن التوزيع مرة واحدة لكل منشور. بعد اكتمال الهدف، ينتقل الحساب تلقائياً إلى مسار المغادرة قبل أن يصبح متاحاً مجدداً.</p></div></div></section>
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6"><div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">ACTIVE CAMPAIGN</p><h3 className="mt-1 text-base font-bold">الحملة الحالية</h3></div><Link href="/campaigns" data-testid="link-view-campaigns" className="text-[11px] font-bold text-primary hover:underline">عرض الكل</Link></div>{campaigns.isLoading ? <Skeleton className="h-32 w-full" /> : activeCampaign ? <div className="rounded-xl border border-border bg-muted/40 p-4"><div className="mb-4 flex items-start justify-between gap-3"><div><StatusBadge tone="teal">نشطة الآن</StatusBadge><h4 className="mt-3 text-sm font-bold">{activeCampaign.name}</h4><p className="mt-1 text-xs text-muted-foreground">{activeCampaign.channel} · تنتهي {date(activeCampaign.endDate)}</p></div><span className="rounded-lg bg-card px-2 py-1 font-mono text-[10px] text-muted-foreground">#{activeCampaign.id}</span></div><div className="grid grid-cols-2 gap-3 border-t border-border pt-4"><div><span className="block font-mono text-lg font-semibold">{number(activeCampaign.postsCount)}</span><span className="text-[10px] text-muted-foreground">منشور مؤهل</span></div><div><span className="block font-mono text-lg font-semibold">{number(activeCampaign.reactionsPerPost)}</span><span className="text-[10px] text-muted-foreground">تفاعل / منشور</span></div></div></div> : <div className="flex min-h-32 flex-col items-center justify-center rounded-xl border border-dashed border-border text-center"><p className="text-sm font-semibold">لا توجد حملة نشطة</p><Link href="/campaigns" data-testid="link-create-first-campaign" className="mt-2 text-xs font-bold text-primary">أنشئ حملة جديدة</Link></div>}</section>
    </div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.45fr_.8fr]">
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6"><div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">CURRENT POSTS</p><h3 className="mt-1 text-base font-bold">المنشورات الحالية</h3></div><Link href="/posts" data-testid="link-view-posts" className="text-[11px] font-bold text-primary hover:underline">فتح الطابور <ChevronLeft className="inline h-3 w-3" /></Link></div><QueryState loading={posts.isLoading} error={!!posts.error} empty={!latestPosts.length} retry={refresh}><div className="space-y-2">{latestPosts.map((post) => <PostRow key={post.id} post={post} onOpen={() => setSelectedPost(post.id)} onRetry={() => { retry.mutate({ id: post.id }, { onSuccess: () => qc.invalidateQueries({ queryKey: getListPostsQueryKey({ status: 'all' }) }) }); }} retrying={retry.isPending && retry.variables?.id === post.id} />)}</div></QueryState></section>
      <section className="rounded-2xl border border-border bg-card p-5 sm:p-6"><div className="mb-5 flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">RECENT ACTIVITY</p><h3 className="mt-1 text-base font-bold">آخر النشاط</h3></div><ActivityIcon className="h-4 w-4 text-muted-foreground" /></div><QueryState loading={activity.isLoading} error={!!activity.error} empty={!activity.data?.length} retry={() => activity.refetch()}><ActivityList items={(activity.data ?? []).slice(0, 6)} /></QueryState></section>
    </div>
    {selectedPost && <Modal title="تفاصيل المنشور" eyebrow="Post inspection" onClose={() => setSelectedPost(null)}><QueryState loading={selected.isLoading} error={!!selected.error} retry={() => selected.refetch()}>{selected.data && <PostDetail post={selected.data} />}</QueryState></Modal>}
  </div>;
}

function PostRow({ post, onOpen, onRetry, retrying }: { post: Post; onOpen: () => void; onRetry: () => void; retrying?: boolean }) {
  return <div className="flex flex-col gap-3 rounded-xl border border-border/70 p-3.5 transition-colors hover:border-primary/30 hover:bg-primary/[.025] sm:flex-row sm:items-center"><button data-testid={`button-open-post-${post.id}`} onClick={onOpen} className="min-w-0 flex-1 text-right"><div className="mb-1 flex items-center gap-2"><span className="truncate text-xs font-bold">{post.content}</span><StatusBadge tone={statusTone(post.status)}>{statusLabel(post.status)}</StatusBadge></div><p className="text-[11px] text-muted-foreground">{post.campaignName} · {post.channel} · {post.completedReactions}/{post.targetReactions} تفاعل</p></button><div className="flex items-center gap-2 self-end sm:self-auto">{post.status === 'failed' && <button data-testid={`button-retry-post-${post.id}`} onClick={onRetry} disabled={retrying} className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/20 px-2.5 py-2 text-[10px] font-bold text-destructive hover:bg-destructive/5 disabled:opacity-50">{retrying ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}إعادة</button>}<button data-testid={`button-inspect-post-${post.id}`} onClick={onOpen} className="rounded-lg p-2 text-muted-foreground hover:bg-muted"><ExternalLink className="h-3.5 w-3.5" /></button></div></div>;
}

function ActivityList({ items }: { items: Activity[] }) {
  return <div className="space-y-4">{items.map((item) => <div key={item.id} data-testid={`activity-item-${item.id}`} className="flex gap-3"><span className={cn('mt-1.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg', item.tone === 'success' ? 'bg-primary/10 text-primary' : item.tone === 'warning' ? 'bg-accent/20 text-amber-700' : 'bg-muted text-muted-foreground')}><span className="h-1.5 w-1.5 rounded-full bg-current" /></span><div className="min-w-0 flex-1"><p className="text-xs font-semibold leading-5">{item.message}</p><p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{timeAgo(item.createdAt)}</p></div></div>)}</div>;
}

function PostDetail({ post }: { post: Post }) {
  return <div className="space-y-5"><div className="rounded-xl bg-muted/60 p-4"><p className="text-sm font-semibold leading-7">{post.content}</p><p className="mt-2 text-xs text-muted-foreground">{post.channel} · نُشر {date(post.publishedAt)}</p></div><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[['الهدف', post.targetReactions], ['المكتمل', post.completedReactions], ['الحالة', statusLabel(post.status)], ['المغادرة', statusLabel(post.leaveStatus)]].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-border p-3"><span className="block text-[10px] text-muted-foreground">{label}</span><span className="mt-1 block text-sm font-bold">{value}</span></div>)}</div></div>;
}

function Campaigns() {
  const campaigns = useListCampaigns();
  const create = useCreateCampaign();
  const update = useUpdateCampaign();
  const qc = useQueryClient();
  const [modal, setModal] = useState(false);
  const [inspect, setInspect] = useState<Campaign | null>(null);
  const [notice, setNotice] = useState('');
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); create.mutate({ data: { name: String(data.get('name')), channel: String(data.get('channel')), durationDays: Number(data.get('durationDays')), reactionsPerPost: Number(data.get('reactionsPerPost')) } }, { onSuccess: () => { setModal(false); setNotice('تم إنشاء الحملة وإضافتها إلى غرفة التشغيل.'); qc.invalidateQueries({ queryKey: getListCampaignsQueryKey() }); qc.invalidateQueries({ queryKey: getGetDashboardSummaryQueryKey() }); } }); };
  const toggle = (campaign: Campaign) => { const next = campaign.status === 'active' ? 'paused' : 'active'; update.mutate({ id: campaign.id, data: { status: next } }, { onSuccess: () => { setNotice(next === 'active' ? 'استؤنفت الحملة بنجاح.' : 'تم إيقاف الحملة مؤقتاً.'); qc.invalidateQueries({ queryKey: getListCampaignsQueryKey() }); qc.invalidateQueries({ queryKey: getGetDashboardSummaryQueryKey() }); } }); };
  return <div className="page-enter"><PageIntro label="نظام التشغيل / campaigns" title="الحملات" description="اضبط مدة الأهلية وعدد التفاعلات الثابت لكل منشور. لا يتغير target بعد بدء التوزيع." action={<button data-testid="button-open-create-campaign" onClick={() => setModal(true)} className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-xs font-bold text-primary-foreground shadow-lg shadow-primary/15 hover:brightness-95"><Plus className="h-4 w-4" />حملة جديدة</button>} />{notice && <div data-testid="status-campaign-feedback" className="mb-5 flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-semibold text-primary"><Check className="h-4 w-4" />{notice}<button data-testid="button-dismiss-campaign-feedback" onClick={() => setNotice('')} className="mr-auto"><X className="h-3.5 w-3.5" /></button></div>}<div className="mb-5 grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-border bg-card p-4"><span className="text-[10px] text-muted-foreground">كل الحملات</span><strong className="mt-2 block font-mono text-2xl">{number(campaigns.data?.length)}</strong></div><div className="rounded-xl border border-border bg-card p-4"><span className="text-[10px] text-muted-foreground">نشطة الآن</span><strong className="mt-2 block font-mono text-2xl text-primary">{number(campaigns.data?.filter((c) => c.status === 'active').length)}</strong></div><div className="rounded-xl border border-border bg-card p-4"><span className="text-[10px] text-muted-foreground">إجمالي التفاعلات المستهدفة</span><strong className="mt-2 block font-mono text-2xl">{number(campaigns.data?.reduce((sum, c) => sum + c.totalReactions, 0))}</strong></div></div><QueryState loading={campaigns.isLoading} error={!!campaigns.error} empty={!campaigns.data?.length} retry={() => campaigns.refetch()}><div className="grid gap-4 lg:grid-cols-2">{(campaigns.data ?? []).map((campaign) => <CampaignCard key={campaign.id} campaign={campaign} onInspect={() => setInspect(campaign)} onToggle={() => toggle(campaign)} pending={update.isPending && update.variables?.id === campaign.id} />)}</div></QueryState>{modal && <Modal title="إنشاء حملة تفاعلات" eyebrow="New campaign" onClose={() => setModal(false)}><form onSubmit={submit} className="space-y-4"><Field label="اسم الحملة"><input data-testid="input-campaign-name" name="name" required placeholder="مثال: إطلاق الربيع — القناة الرئيسية" className="control-input" /></Field><Field label="القناة"><input data-testid="input-campaign-channel" name="channel" required placeholder="Instagram / X / Telegram" className="control-input" /></Field><div className="grid gap-4 sm:grid-cols-2"><Field label="مدة الأهلية" hint="بالأيام"><input data-testid="input-campaign-duration" name="durationDays" type="number" min="1" defaultValue="7" required className="control-input" /></Field><Field label="تفاعلات لكل منشور" hint="ثابت مرة واحدة"><input data-testid="input-campaign-reactions" name="reactionsPerPost" type="number" min="1" defaultValue="3" required className="control-input" /></Field></div><div className="rounded-xl border border-primary/15 bg-primary/5 p-3 text-xs leading-6 text-foreground/75"><strong className="text-primary">قاعدة التنفيذ:</strong> كل منشور مؤهل سيحصل على <span className="font-mono font-bold">reactionsPerPost</span> تفاعلات فقط. بعد الوصول للهدف، يغادر الحساب المعيّن.</div>{create.error && <p className="text-xs font-semibold text-destructive">تعذر إنشاء الحملة. راجع الحقول وحاول مجدداً.</p>}<button data-testid="button-submit-campaign" disabled={create.isPending} className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3 text-sm font-bold text-primary-foreground disabled:opacity-50">{create.isPending && <LoaderCircle className="h-4 w-4 animate-spin" />}إنشاء الحملة</button></form></Modal>}{inspect && <Modal title={inspect.name} eyebrow="Campaign inspection" onClose={() => setInspect(null)}><div className="space-y-5"><div className="flex items-center justify-between"><StatusBadge tone={statusTone(inspect.status)}>{statusLabel(inspect.status)}</StatusBadge><span className="font-mono text-xs text-muted-foreground">#{inspect.id}</span></div><div className="grid grid-cols-2 gap-3">{[['القناة', inspect.channel], ['الأهلية', `${inspect.durationDays} يوم`], ['تفاعلات / منشور', inspect.reactionsPerPost], ['المنشورات', inspect.postsCount], ['تاريخ البدء', date(inspect.startDate)], ['تاريخ الانتهاء', date(inspect.endDate)]].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-border p-3"><span className="block text-[10px] text-muted-foreground">{label}</span><span className="mt-1 block text-sm font-bold">{value}</span></div>)}</div><div className="rounded-xl bg-muted p-4"><div className="mb-2 flex justify-between text-xs"><span>تقدم التفاعلات</span><span className="font-mono">{inspect.completedReactions}/{inspect.totalReactions}</span></div><div className="h-2 rounded-full bg-card"><div className="h-full rounded-full bg-primary" style={{ width: `${inspect.totalReactions ? (inspect.completedReactions / inspect.totalReactions) * 100 : 0}%` }} /></div></div></div></Modal>}</div>;
}

function CampaignCard({ campaign, onInspect, onToggle, pending }: { campaign: Campaign; onInspect: () => void; onToggle: () => void; pending: boolean }) {
  const progress = campaign.totalReactions ? Math.round((campaign.completedReactions / campaign.totalReactions) * 100) : 0;
  return <article data-testid={`card-campaign-${campaign.id}`} className="rounded-2xl border border-border bg-card p-5 shadow-[0_8px_24px_hsl(197_35%_20%/0.04)]"><div className="flex items-start justify-between gap-4"><div className="flex min-w-0 items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-secondary text-secondary-foreground"><Layers3 className="h-4 w-4" /></span><div className="min-w-0"><h3 className="truncate text-sm font-bold">{campaign.name}</h3><p className="mt-1 text-xs text-muted-foreground">{campaign.channel} · {campaign.durationDays} يوم أهلية</p></div></div><StatusBadge tone={statusTone(campaign.status)}>{statusLabel(campaign.status)}</StatusBadge></div><div className="mt-6 grid grid-cols-3 gap-3 border-y border-border py-4"><div><span className="block font-mono text-lg font-semibold">{number(campaign.postsCount)}</span><span className="text-[10px] text-muted-foreground">منشورات</span></div><div><span className="block font-mono text-lg font-semibold">{campaign.reactionsPerPost}</span><span className="text-[10px] text-muted-foreground">تفاعل ثابت</span></div><div><span className="block font-mono text-lg font-semibold">{progress}%</span><span className="text-[10px] text-muted-foreground">مكتمل</span></div></div><div className="mb-5 mt-4 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} /></div><div className="flex gap-2"><button data-testid={`button-inspect-campaign-${campaign.id}`} onClick={onInspect} className="flex-1 rounded-xl border border-border py-2.5 text-xs font-bold hover:bg-muted">تفاصيل الحملة</button>{campaign.status !== 'expired' && <button data-testid={`button-toggle-campaign-${campaign.id}`} onClick={onToggle} disabled={pending} className={cn('flex-1 inline-flex items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-bold', campaign.status === 'active' ? 'bg-accent/20 text-amber-800 hover:bg-accent/30' : 'bg-primary text-primary-foreground hover:brightness-95')}>{pending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : campaign.status === 'active' ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}{campaign.status === 'active' ? 'إيقاف مؤقت' : 'استئناف'}</button>}</div></article>;
}

function Posts() {
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedPost, setSelectedPost] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const posts = useListPosts({ status: statusFilter === 'all' ? 'all' : statusFilter as 'queued' | 'processing' | 'completed' | 'failed' });
  const campaigns = useListCampaigns();
  const create = useCreatePost();
  const retry = useRetryPost();
  const qc = useQueryClient();
  const selected = useGetPost(selectedPost ?? 0, { query: { enabled: !!selectedPost, queryKey: getGetPostQueryKey(selectedPost ?? 0) } });
  const filtered = useMemo(() => (posts.data ?? []).filter((post) => `${post.content} ${post.campaignName} ${post.channel}`.toLowerCase().includes(search.toLowerCase())), [posts.data, search]);
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); create.mutate({ data: { campaignId: Number(data.get('campaignId')), channel: String(data.get('channel')), telegramUrl: String(data.get('telegramUrl')), content: String(data.get('content')) } }, { onSuccess: () => { setCreateOpen(false); setNotice('تمت إضافة المنشور إلى الطابور.'); qc.invalidateQueries({ queryKey: getListPostsQueryKey({ status: 'all' }) }); qc.invalidateQueries({ queryKey: getGetDashboardSummaryQueryKey() }); } }); };
  const doRetry = (id: number) => retry.mutate({ id }, { onSuccess: () => { setNotice('أعيد إدراج المنشور في الطابور.'); qc.invalidateQueries({ queryKey: getListPostsQueryKey({ status: statusFilter === 'all' ? 'all' : statusFilter as 'queued' }) }); } });
  return <div className="page-enter"><PageIntro label="نظام التشغيل / queue" title="طابور المنشورات" description="أضف رابط Telegram العام. عدد التفاعلات يؤخذ من إعداد الحملة مرة واحدة لكل منشور، ثم يبدأ مؤقت المغادرة للحسابات المنفذة." action={<button data-testid="button-open-create-post" onClick={() => setCreateOpen(true)} className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-xs font-bold text-primary-foreground shadow-lg shadow-primary/15 hover:brightness-95"><Plus className="h-4 w-4" />إضافة منشور</button>} />{notice && <div data-testid="status-post-feedback" className="mb-5 flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-semibold text-primary"><Check className="h-4 w-4" />{notice}<button data-testid="button-dismiss-post-feedback" onClick={() => setNotice('')} className="mr-auto"><X className="h-3.5 w-3.5" /></button></div>}<div className="mb-5 flex flex-col gap-3 rounded-2xl border border-border bg-card p-3 sm:flex-row"><div className="relative flex-1"><Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><input data-testid="input-search-posts" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ابحث في النص، الحملة، أو القناة..." className="control-input pr-10" /></div><div className="flex items-center gap-2 overflow-x-auto">{['all', 'queued', 'processing', 'completed', 'failed'].map((status) => <button key={status} data-testid={`button-filter-posts-${status}`} onClick={() => setStatusFilter(status)} className={cn('whitespace-nowrap rounded-lg px-3 py-2 text-xs font-bold', statusFilter === status ? 'bg-secondary text-secondary-foreground' : 'text-muted-foreground hover:bg-muted')}>{status === 'all' ? 'الكل' : statusLabel(status)}</button>)}</div><button data-testid="button-advanced-post-filter" className="hidden rounded-lg border border-border p-2 text-muted-foreground hover:bg-muted sm:block"><Filter className="h-4 w-4" /></button></div><QueryState loading={posts.isLoading} error={!!posts.error} empty={!filtered.length} retry={() => posts.refetch()}><div className="overflow-hidden rounded-2xl border border-border bg-card"><div className="hidden grid-cols-[1.6fr_.85fr_.55fr_.7fr_.8fr] gap-4 border-b border-border bg-muted/50 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground md:grid"><span>المنشور</span><span>التقدم</span><span>الحالة</span><span>المغادرة</span><span>إجراء</span></div><div className="divide-y divide-border">{filtered.map((post) => <PostTableRow key={post.id} post={post} onOpen={() => setSelectedPost(post.id)} onRetry={() => doRetry(post.id)} retrying={retry.isPending && retry.variables?.id === post.id} />)}</div></div></QueryState>{selectedPost && <Modal title="تفاصيل المنشور" eyebrow="Post inspection" onClose={() => setSelectedPost(null)}><QueryState loading={selected.isLoading} error={!!selected.error} retry={() => selected.refetch()}>{selected.data && <PostDetail post={selected.data} />}</QueryState></Modal>}{createOpen && <Modal title="إضافة منشور للطابور" eyebrow="Enroll post" onClose={() => setCreateOpen(false)}><form onSubmit={submit} className="space-y-4"><Field label="الحملة"><select data-testid="select-post-campaign" name="campaignId" required className="control-input" defaultValue={campaigns.data?.[0]?.id ?? ''}>{(campaigns.data ?? []).map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}</select></Field><Field label="رابط منشور Telegram العام"><input data-testid="input-post-telegram-url" name="telegramUrl" type="url" required placeholder="https://t.me/channel/123" className="control-input" /></Field><Field label="القناة"><input data-testid="input-post-channel" name="channel" required placeholder="@channel" className="control-input" /></Field><Field label="نص المنشور"><textarea data-testid="input-post-content" name="content" required rows={4} placeholder="ألصق نص المنشور هنا..." className="control-input resize-none" /></Field><div className="rounded-xl border border-primary/15 bg-primary/5 p-3 text-xs leading-6 text-foreground/75"><strong className="text-primary">الهدف:</strong> سيستخدم النظام عدد التفاعلات المحدد في الحملة، وليس عددًا يوميًا.</div>{create.error && <p className="text-xs font-semibold text-destructive">تعذر إضافة المنشور.</p>}<button data-testid="button-submit-post" disabled={create.isPending || !campaigns.data?.length} className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3 text-sm font-bold text-primary-foreground disabled:opacity-50">{create.isPending && <LoaderCircle className="h-4 w-4 animate-spin" />}إضافة إلى الطابور</button></form></Modal>}</div>;
}

function PostTableRow({ post, onOpen, onRetry, retrying }: { post: Post; onOpen: () => void; onRetry: () => void; retrying?: boolean }) {
  const progress = post.targetReactions ? Math.min(100, Math.round((post.completedReactions / post.targetReactions) * 100)) : 0;
  return <div data-testid={`row-post-${post.id}`} className="grid gap-3 px-4 py-4 transition-colors hover:bg-muted/30 md:grid-cols-[1.6fr_.85fr_.55fr_.7fr_.8fr] md:items-center md:gap-4 md:px-5"><button data-testid={`button-open-queue-post-${post.id}`} onClick={onOpen} className="min-w-0 text-right"><div className="flex items-center gap-2"><span className="truncate text-xs font-bold">{post.content}</span><ArrowLeft className="h-3 w-3 shrink-0 text-muted-foreground md:hidden" /></div><p className="mt-1 truncate text-[10px] text-muted-foreground">{post.campaignName} · {post.channel} · {date(post.publishedAt)}</p></button><div><div className="mb-1 flex justify-between text-[10px]"><span className="font-mono">{post.completedReactions}/{post.targetReactions}</span><span className="text-muted-foreground md:hidden">التقدم</span></div><div className="h-1.5 rounded-full bg-muted"><div className={cn('h-full rounded-full', progress === 100 ? 'bg-primary' : 'bg-sky-500')} style={{ width: `${progress}%` }} /></div></div><div><span className="text-[10px] text-muted-foreground md:hidden">الحالة: </span><StatusBadge tone={statusTone(post.status)}>{statusLabel(post.status)}</StatusBadge></div><div><span className="text-[10px] text-muted-foreground md:hidden">المغادرة: </span><span className="text-[11px] font-semibold">{statusLabel(post.leaveStatus)}</span></div><div className="flex items-center gap-2"><button data-testid={`button-inspect-queue-post-${post.id}`} onClick={onOpen} className="rounded-lg border border-border p-2 text-muted-foreground hover:bg-muted"><ExternalLink className="h-3.5 w-3.5" /></button>{post.status === 'failed' && <button data-testid={`button-retry-queue-post-${post.id}`} onClick={onRetry} disabled={retrying} className="rounded-lg border border-destructive/20 p-2 text-destructive hover:bg-destructive/5 disabled:opacity-50">{retrying ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}</button>}</div></div>;
}

function Accounts() {
  const accounts = useListAccounts();
  const [search, setSearch] = useState('');
  const filtered = useMemo(() => (accounts.data ?? []).filter((account) => account.handle.toLowerCase().includes(search.toLowerCase())), [accounts.data, search]);
  const counts = { available: accounts.data?.filter((a) => a.status === 'available').length ?? 0, reacting: accounts.data?.filter((a) => a.status === 'reacting').length ?? 0, leaving: accounts.data?.filter((a) => a.status === 'leaving').length ?? 0, cooldown: accounts.data?.filter((a) => a.status === 'cooldown').length ?? 0 };
  return <div className="page-enter"><PageIntro label="نظام التشغيل / accounts" title="مجموعة الحسابات" description="راقب التوفر ومسار ما بعد التفاعل. الحساب لا يعود إلى pool المتاح قبل اكتمال إجراء المغادرة." action={<button data-testid="button-refresh-accounts" onClick={() => accounts.refetch()} className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-xs font-bold shadow-sm hover:bg-muted"><RefreshCw className={cn('h-4 w-4', accounts.isFetching && 'animate-spin')} />تحديث المجموعة</button>} /><div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4"><AccountCount label="متاح" value={counts.available} tone="teal" /><AccountCount label="يتفاعل الآن" value={counts.reacting} tone="blue" /><AccountCount label="في مسار المغادرة" value={counts.leaving} tone="amber" /><AccountCount label="فترة تهدئة" value={counts.cooldown} tone="slate" /></div><div className="mb-5 flex items-center gap-3 rounded-2xl border border-border bg-card p-3"><div className="relative flex-1"><Search className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><input data-testid="input-search-accounts" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ابحث عن handle..." className="control-input pr-10" /></div><span className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex"><ServerCog className="h-4 w-4" />{number(accounts.data?.length)} حساب مسجل</span></div><QueryState loading={accounts.isLoading} error={!!accounts.error} empty={!filtered.length} retry={() => accounts.refetch()}><div className="overflow-hidden rounded-2xl border border-border bg-card"><div className="hidden grid-cols-[1.35fr_.8fr_.7fr_1fr] gap-4 border-b border-border bg-muted/50 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground md:grid"><span>الحساب</span><span>الحالة</span><span>إجمالي التفاعلات</span><span>آخر إجراء</span></div><div className="divide-y divide-border">{filtered.map((account) => <AccountRow key={account.id} account={account} />)}</div></div></QueryState></div>;
}

function AccountCount({ label, value, tone }: { label: string; value: number; tone: 'teal' | 'blue' | 'amber' | 'slate' }) {
  return <div className="rounded-2xl border border-border bg-card p-4"><div className="mb-3 flex items-center gap-2"><StatusDot tone={tone === 'blue' ? 'blue' : tone === 'amber' ? 'amber' : tone === 'slate' ? 'slate' : 'teal'} /><span className="text-xs text-muted-foreground">{label}</span></div><strong className="font-mono text-2xl">{number(value)}</strong></div>;
}

function AccountRow({ account }: { account: Account }) {
  return <div data-testid={`row-account-${account.id}`} className="grid gap-3 px-4 py-4 md:grid-cols-[1.35fr_.8fr_.7fr_1fr] md:items-center md:gap-4 md:px-5"><div className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-full bg-secondary text-xs font-bold text-secondary-foreground">{account.handle.replace('@', '').slice(0, 2).toUpperCase()}</span><div><p className="text-xs font-bold">{account.handle}</p><p className="font-mono text-[10px] text-muted-foreground">ID {account.id}</p></div></div><div><span className="text-[10px] text-muted-foreground md:hidden">الحالة: </span><StatusBadge tone={statusTone(account.status)}>{statusLabel(account.status)}</StatusBadge></div><div><span className="text-[10px] text-muted-foreground md:hidden">التفاعلات: </span><span className="font-mono text-sm font-semibold">{number(account.totalReactions)}</span></div><div><span className="text-[10px] text-muted-foreground md:hidden">آخر إجراء: </span><span className="text-xs text-muted-foreground">{account.lastAction ? timeAgo(account.lastAction) : 'لم يُسجل بعد'}</span></div></div>;
}

function Router() {
  return <ErrorBoundary><Shell><Switch><Route path="/" component={Overview} /><Route path="/campaigns" component={Campaigns} /><Route path="/posts" component={Posts} /><Route path="/accounts" component={Accounts} /><Route component={NotFound} /></Switch></Shell></ErrorBoundary>;
}

function App() {
  return <QueryClientProvider client={queryClient}><TooltipProvider><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><Router /></WouterRouter><Toaster /></TooltipProvider></QueryClientProvider>;
}

export default App;