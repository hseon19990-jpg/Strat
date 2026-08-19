import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  ArrowLeft,
  ArrowUpLeft,
  Bell,
  BookOpen,
  BriefcaseBusiness,
  Check,
  ChevronLeft,
  CircleHelp,
  Crown,
  Gem,
  Home as HomeIcon,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Menu,
  MessageCircle,
  MoreHorizontal,
  Settings2,
  Sparkles,
  Target,
  Users,
  X,
} from 'lucide-react';
import NotFound from '@/pages/not-found';
import { Link, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';

const queryClient = new QueryClient();
const VISIBILITY_KEY = 'strat-services-visible-v1';

type Role = 'member' | 'owner';

function readServicesVisibility() {
  if (typeof window === 'undefined') return true;
  try {
    const stored = window.localStorage.getItem(VISIBILITY_KEY);
    return stored === null ? true : stored === 'true';
  } catch {
    return true;
  }
}

function AppShell({
  role,
  setRole,
  servicesVisible,
  children,
}: {
  role: Role;
  setRole: (role: Role) => void;
  servicesVisible: boolean;
  children: ReactNode;
}) {
  const [location] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notice, setNotice] = useState('');

  const navigation = useMemo(
    () => [
      { label: 'الرئيسية', href: '/', icon: HomeIcon, visible: true },
      { label: 'خدمات أسطورية', href: '/services', icon: Gem, visible: servicesVisible },
      { label: 'دليل الأعضاء', href: '/', icon: Users, visible: true, notice: 'دليل الأعضاء قيد التحديث — سيظهر قريباً.' },
      { label: 'المعرفة', href: '/', icon: BookOpen, visible: true, notice: 'مكتبة المعرفة تُفتح قريباً.' },
    ],
    [servicesVisible],
  );

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(''), 3000);
  };

  return (
    <div dir="rtl" className="min-h-[100dvh] bg-background text-foreground">
      <div className="pointer-events-none fixed inset-0 z-0 opacity-40 [background-image:radial-gradient(hsl(var(--primary)/0.12)_1px,transparent_1px)] [background-size:22px_22px]" />
      <aside
        className={`fixed inset-y-0 right-0 z-40 flex w-[282px] flex-col border-l border-sidebar-border bg-sidebar px-5 py-6 text-sidebar-foreground transition-transform duration-300 md:translate-x-0 ${mobileOpen ? 'translate-x-0' : 'translate-x-full'}`}
      >
        <div className="mb-10 flex items-center justify-between">
          <Link href="/" data-testid="link-brand" className="group flex items-center gap-3">
            <span className="grid size-11 place-items-center rounded-2xl bg-sidebar-primary text-sidebar-primary-foreground shadow-[0_8px_20px_hsl(var(--sidebar-primary)/0.2)] transition-transform duration-300 group-hover:-rotate-6">
              <Crown className="size-5" strokeWidth={2.2} />
            </span>
            <span>
              <span className="block font-mono text-[10px] uppercase tracking-[0.32em] text-sidebar-primary">STRAT / 01</span>
              <span className="block text-lg font-bold tracking-tight">بوابة الأعضاء</span>
            </span>
          </Link>
          <button onClick={() => setMobileOpen(false)} className="rounded-xl p-2 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground md:hidden" data-testid="button-close-menu">
            <X className="size-5" />
          </button>
        </div>

        <div className="mb-7 rounded-2xl border border-sidebar-border bg-sidebar-accent/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold text-sidebar-foreground/55">
            <span className="size-2 rounded-full bg-[#79c8b1]" />
            جلسة المعاينة نشطة
          </div>
          <p className="text-sm font-semibold">{role === 'owner' ? 'وضع المالك' : 'وضع العضو'}</p>
          <p className="mt-1 text-xs leading-5 text-sidebar-foreground/60">
            {role === 'owner' ? 'تظهر لك أدوات إدارة البوابة.' : 'تتصفح البوابة بصلاحيات العضو.'}
          </p>
        </div>

        <nav className="space-y-1.5" aria-label="التنقل الرئيسي">
          <p className="mb-3 px-3 text-[10px] font-bold tracking-[0.22em] text-sidebar-foreground/35">المساحة الشخصية</p>
          {navigation.filter((item) => item.visible).map((item) => {
            const Icon = item.icon;
            const active = location === item.href && !item.notice;
            return item.notice ? (
              <button
                key={item.label}
                onClick={() => showNotice(item.notice ?? '')}
                data-testid={`button-nav-${item.label}`}
                className="group flex w-full items-center gap-3 rounded-xl px-3 py-3 text-right text-sm text-sidebar-foreground/65 transition-all hover:bg-sidebar-accent hover:text-sidebar-foreground"
              >
                <Icon className="size-[18px] text-sidebar-foreground/45 transition-colors group-hover:text-sidebar-primary" />
                <span>{item.label}</span>
                <MoreHorizontal className="mr-auto size-4 opacity-30" />
              </button>
            ) : (
              <Link
                key={item.label}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                data-testid={`link-nav-${item.label}`}
                className={`group flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-all ${active ? 'bg-sidebar-primary font-bold text-sidebar-primary-foreground shadow-[0_10px_24px_hsl(var(--sidebar-primary)/0.13)]' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`}
              >
                <Icon className={`size-[18px] ${active ? '' : 'text-sidebar-foreground/45 transition-colors group-hover:text-sidebar-primary'}`} />
                <span>{item.label}</span>
                {item.label === 'خدمات أسطورية' && <Sparkles className={`mr-auto size-3.5 ${active ? 'opacity-100' : 'text-sidebar-primary'}`} />}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto">
          {role === 'owner' && (
            <Link href="/owner-settings" onClick={() => setMobileOpen(false)} data-testid="link-owner-settings" className={`mb-2 flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-all ${location === '/owner-settings' ? 'bg-sidebar-accent text-sidebar-primary' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`}>
              <Settings2 className="size-[18px]" />
              <span>إعدادات المالك</span>
              <ArrowLeft className="mr-auto size-4 opacity-50" />
            </Link>
          )}
          <button onClick={() => setRole(role === 'owner' ? 'member' : 'owner')} data-testid="button-role-switcher" className="flex w-full items-center gap-3 rounded-xl border border-sidebar-border px-3 py-3 text-right text-xs text-sidebar-foreground/65 transition-colors hover:border-sidebar-primary/50 hover:bg-sidebar-accent">
            {role === 'owner' ? <LockKeyhole className="size-4 text-sidebar-primary" /> : <Settings2 className="size-4 text-sidebar-primary" />}
            <span className="flex-1">{role === 'owner' ? 'معاينة العضو' : 'معاينة المالك'}</span>
            <ArrowUpLeft className="size-3.5 opacity-50" />
          </button>
          <div className="mt-6 border-t border-sidebar-border pt-4 text-center font-mono text-[9px] tracking-[0.25em] text-sidebar-foreground/25">A COMMUNITY WITH A POINT OF VIEW</div>
        </div>
      </aside>

      <div className="relative z-10 min-h-[100dvh] md:mr-[282px]">
        <header className="sticky top-0 z-30 flex h-[76px] items-center justify-between border-b border-border/70 bg-background/85 px-5 backdrop-blur-xl md:px-10">
          <div className="flex items-center gap-3">
            <button onClick={() => setMobileOpen(true)} className="rounded-xl border border-border bg-card p-2.5 md:hidden" data-testid="button-open-menu"><Menu className="size-5" /></button>
            <div>
              <p className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground">SATURDAY / 18 MAY 2024</p>
              <p className="mt-1 text-xs font-semibold text-muted-foreground">مساحتك في Strat</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => showNotice('لا توجد تنبيهات جديدة الآن.')} className="relative rounded-xl border border-border bg-card p-2.5 text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground" data-testid="button-notifications">
              <Bell className="size-[18px]" />
              <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-[#d77b62]" />
            </button>
            <div className="hidden h-8 w-px bg-border sm:block" />
            <button onClick={() => setRole(role === 'owner' ? 'member' : 'owner')} className="flex items-center gap-2.5 text-right" data-testid="button-profile-role">
              <span className="grid size-9 place-items-center rounded-xl bg-[#e9c46a] font-bold text-[#263246]">س</span>
              <span className="hidden sm:block"><span className="block text-xs font-bold">سارة العتيبي</span><span className="block text-[10px] text-muted-foreground">{role === 'owner' ? 'مالك المجتمع' : 'عضو منذ 2022'}</span></span>
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-[1380px] px-5 py-8 md:px-10 md:py-12">{children}</main>
      </div>

      {notice && <div role="status" data-testid="status-notice" className="fixed bottom-5 left-5 z-50 flex max-w-sm items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 text-sm font-semibold shadow-xl animate-in slide-in-from-bottom-3">{notice}<button onClick={() => setNotice('')} data-testid="button-dismiss-notice" className="mr-auto text-muted-foreground hover:text-foreground"><X className="size-4" /></button></div>}
    </div>
  );
}

function Home() {
  const [, setLocation] = useLocation();
  const quickItems = [
    { title: 'خدمات أسطورية', description: 'تجارب وخدمات صُممت لأعضاء Strat', icon: Gem, href: '/services', accent: 'bg-[#f4e6b7] text-[#735817]', test: 'link-quick-services' },
    { title: 'دليل الأعضاء', description: 'اعثر على شخص يفكر مثلك', icon: Users, href: '/', accent: 'bg-[#d6ebe4] text-[#2c7768]', test: 'button-quick-members', notice: 'دليل الأعضاء قيد التحديث — سيظهر قريباً.' },
    { title: 'المعرفة', description: 'أفكار تستحق أن تبقى معك', icon: BookOpen, href: '/', accent: 'bg-[#e6dff0] text-[#66517f]', test: 'button-quick-library', notice: 'مكتبة المعرفة تُفتح قريباً.' },
  ];
  const [notice, setNotice] = useState('');
  const showNotice = (text: string) => { setNotice(text); window.setTimeout(() => setNotice(''), 2800); };
  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-[28px] bg-primary px-6 py-9 text-primary-foreground shadow-[0_24px_50px_hsl(var(--primary)/0.13)] md:px-12 md:py-12">
        <div className="absolute -left-16 -top-24 size-72 rounded-full border-[28px] border-accent/15" />
        <div className="absolute -bottom-28 left-24 size-64 rounded-full border border-primary-foreground/10" />
        <div className="relative max-w-2xl">
          <div className="mb-6 flex items-center gap-2 text-accent"><Sparkles className="size-4" /><span className="text-xs font-bold tracking-wide">صباح الخير يا سارة</span></div>
          <h1 className="max-w-xl text-3xl font-bold leading-[1.35] tracking-tight md:text-5xl">مكانك الذي يبدأ منه<br /><span className="text-accent">الشيء المختلف.</span></h1>
          <p className="mt-5 max-w-lg text-sm leading-7 text-primary-foreground/65 md:text-base">كل ما تحتاجينه لتبقي قريبة من الأفكار، الأشخاص، والفرص التي تصنع أثراً حقيقياً.</p>
          <button onClick={() => setLocation('/services')} data-testid="button-hero-services" className="mt-8 inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-3 text-sm font-bold text-accent-foreground transition-transform duration-200 hover:-translate-y-0.5">استكشفي خدماتك <ChevronLeft className="size-4" /></button>
        </div>
        <div className="absolute bottom-8 left-10 hidden text-left md:block"><p className="font-mono text-[9px] tracking-[0.25em] text-primary-foreground/35">STRAT MEMBER / 0248</p><p className="mt-3 text-4xl font-bold text-primary-foreground/10">STAY<br />CURIOUS.</p></div>
      </section>

      <section>
        <div className="mb-5 flex items-end justify-between"><div><p className="font-mono text-[10px] tracking-[0.22em] text-muted-foreground">YOUR SPACE</p><h2 className="mt-1 text-2xl font-bold">مساحتك في Strat</h2></div><button onClick={() => showNotice('ستظهر كل المساحات هنا قريباً.')} data-testid="button-view-all-spaces" className="text-xs font-bold text-muted-foreground transition-colors hover:text-primary">عرض الكل</button></div>
        <div className="grid gap-4 md:grid-cols-3">
          {quickItems.map((item) => { const Icon = item.icon; return item.notice ? <button key={item.title} onClick={() => showNotice(item.notice ?? '')} data-testid={item.test} className="group flex min-h-[170px] flex-col justify-between rounded-2xl border border-border bg-card p-5 text-right transition-all duration-300 hover:-translate-y-1 hover:border-primary/20 hover:shadow-[0_14px_30px_hsl(var(--primary)/0.07)]"><span className={`grid size-11 place-items-center rounded-xl ${item.accent}`}><Icon className="size-5" /></span><span><span className="flex items-center gap-2 font-bold">{item.title}<ArrowLeft className="size-4 text-muted-foreground transition-transform group-hover:-translate-x-1" /></span><span className="mt-1 block text-xs text-muted-foreground">{item.description}</span></span></button> : <Link key={item.title} href={item.href} data-testid={item.test} className="group flex min-h-[170px] flex-col justify-between rounded-2xl border border-border bg-card p-5 text-right transition-all duration-300 hover:-translate-y-1 hover:border-primary/20 hover:shadow-[0_14px_30px_hsl(var(--primary)/0.07)]"><span className={`grid size-11 place-items-center rounded-xl ${item.accent}`}><Icon className="size-5" /></span><span><span className="flex items-center gap-2 font-bold">{item.title}<ArrowLeft className="size-4 text-muted-foreground transition-transform group-hover:-translate-x-1" /></span><span className="mt-1 block text-xs text-muted-foreground">{item.description}</span></span></Link>; })}
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
        <div className="rounded-2xl border border-border bg-card p-6 md:p-7">
          <div className="mb-7 flex items-center justify-between"><div><p className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground">MEMBER PULSE</p><h2 className="mt-1 text-xl font-bold">نبض المجتمع</h2></div><span className="rounded-full bg-secondary px-3 py-1 text-[10px] font-bold text-secondary-foreground">هذا الأسبوع</span></div>
          <div className="flex items-end gap-1.5 border-b border-border pb-5 pt-3">{[34, 48, 42, 62, 54, 76, 68, 86, 72, 92, 78, 100].map((height, index) => <div key={index} className="group flex flex-1 flex-col items-center gap-2"><div style={{ height: `${height}px` }} className={`w-full max-w-[22px] rounded-t-md transition-transform duration-300 group-hover:-translate-y-1 ${index === 9 ? 'bg-accent' : 'bg-[#c6dcd5]'}`} /><span className="font-mono text-[8px] text-muted-foreground">{['س','ح','ن','ث','ر','خ'][index % 6]}</span></div>)}</div>
          <p className="mt-5 text-xs leading-6 text-muted-foreground">الحوارات هذا الأسبوع تدور حول <strong className="text-foreground">صناعة الأثر</strong> وطرق تحويل الفضول إلى بداية.</p>
        </div>
        <div className="rounded-2xl border border-border bg-[#e3f0eb] p-6 text-[#244d45] md:p-7">
          <div className="flex size-10 items-center justify-center rounded-xl bg-[#b9d8ce]"><Target className="size-5" /></div>
          <p className="mt-10 font-mono text-[10px] tracking-[0.2em] text-[#547d72]">YOUR NEXT MOVE</p>
          <h2 className="mt-2 text-xl font-bold leading-8">خطوة صغيرة،<br />فرق كبير.</h2>
          <p className="mt-3 text-xs leading-6 text-[#547d72]">تصفحي الخدمات المتاحة لك واختاري ما يناسب خطوتك القادمة.</p>
          <Link href="/services" data-testid="link-next-move" className="mt-6 inline-flex items-center gap-2 text-xs font-bold text-[#244d45]">اكتشفي المزيد <ArrowLeft className="size-4" /></Link>
        </div>
      </section>
      {notice && <div role="status" data-testid="status-home-notice" className="fixed bottom-5 left-5 z-40 rounded-2xl border border-border bg-card px-4 py-3 text-sm font-semibold shadow-xl">{notice}</div>}
    </div>
  );
}

function Services({ visible }: { visible: boolean }) {
  const [, setLocation] = useLocation();
  const [notice, setNotice] = useState('');
  const cards = [
    { title: 'جلسة وضوح', type: 'جلسة فردية', description: 'ساعة واحدة لترتيب الفكرة، تحديد السؤال الصحيح، والخروج بخطوة عملية.', icon: Target, color: 'bg-[#f4e6b7] text-[#735817]' },
    { title: 'مائدة Strat', type: 'لقاء شهري', description: 'مساحة حميمة للقاء أعضاء يشاركونك الفضول، بعيداً عن الضجيج المعتاد.', icon: Users, color: 'bg-[#d6ebe4] text-[#2c7768]' },
    { title: 'مختبر الفكرة', type: 'برنامج قصير', description: 'نحوّل الفكرة الخام إلى تجربة قابلة للاختبار خلال ثلاث لقاءات مركزة.', icon: Sparkles, color: 'bg-[#e6dff0] text-[#66517f]' },
    { title: 'مكتب الخبرة', type: 'مكتبة خاصة', description: 'أدوات، قوالب، وملاحظات من تجارب أعضاء المجتمع — متاحة لك متى احتجتها.', icon: BriefcaseBusiness, color: 'bg-[#f1d9cc] text-[#925844]' },
  ];
  if (!visible) return <AccessDenied title="هذه المساحة غير متاحة حالياً" description="أخفى مالك المجتمع خدمات أسطورية مؤقتاً. عودي لاحقاً أو تواصلي مع فريق Strat." onBack={() => setLocation('/')} />;
  return <div className="space-y-9">
    <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><p className="font-mono text-[10px] tracking-[0.22em] text-muted-foreground">THE LEGENDARY DESK / 02</p><h1 className="mt-2 text-3xl font-bold tracking-tight md:text-4xl">خدمات أسطورية</h1><p className="mt-3 max-w-xl text-sm leading-7 text-muted-foreground">ليست قائمة خدمات. إنها مساحات صُممت لتجعلك أقرب إلى النسخة التي تبحثين عنها.</p></div><span className="w-fit rounded-full border border-accent/50 bg-accent/20 px-4 py-2 text-xs font-bold text-[#735817]">متاحة لأعضاء Strat</span></div>
    <div className="grid gap-4 md:grid-cols-2">
      {cards.map((card, index) => { const Icon = card.icon; return <article key={card.title} className="group relative overflow-hidden rounded-2xl border border-border bg-card p-6 transition-all duration-300 hover:-translate-y-1 hover:border-primary/20 hover:shadow-[0_18px_35px_hsl(var(--primary)/0.07)]"><span className="absolute left-5 top-5 font-mono text-[10px] text-muted-foreground/60">0{index + 1}</span><span className={`grid size-12 place-items-center rounded-2xl ${card.color}`}><Icon className="size-5" /></span><p className="mt-8 text-[10px] font-bold tracking-[0.16em] text-muted-foreground">{card.type}</p><h2 className="mt-2 text-xl font-bold">{card.title}</h2><p className="mt-3 min-h-[54px] text-sm leading-7 text-muted-foreground">{card.description}</p><button onClick={() => { setNotice(`سيتم فتح طلب «${card.title}» قريباً.`); window.setTimeout(() => setNotice(''), 2800); }} data-testid={`button-request-${index}`} className="mt-6 inline-flex items-center gap-2 text-xs font-bold text-primary transition-colors hover:text-[#b28a24]">اعرفي أكثر <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-1" /></button></article>; })}
    </div>
    <div className="flex items-center gap-4 rounded-2xl border border-dashed border-border p-5 text-muted-foreground"><CircleHelp className="size-5 shrink-0 text-accent-foreground" /><p className="text-xs leading-6">لم تجدي ما تبحثين عنه؟ <button onClick={() => setNotice('أرسلي لنا رسالتك من مساحة التواصل قريباً.')} data-testid="button-contact-services" className="font-bold text-foreground underline decoration-accent underline-offset-4">تحدثي مع فريق Strat</button></p>{notice && <span role="status" data-testid="status-services-notice" className="mr-auto text-xs font-bold text-foreground">{notice}</span>}</div>
  </div>;
}

function OwnerSettings({ role, visible, onToggle }: { role: Role; visible: boolean; onToggle: () => void }) {
  const [, setLocation] = useLocation();
  if (role !== 'owner') return <AccessDenied title="هذه المساحة للمالك فقط" description="إعدادات ظهور الخدمات محفوظة لصاحب المجتمع. يمكنك العودة إلى لوحتك ومتابعة التصفح كعضو." onBack={() => setLocation('/')} />;
  return <div className="mx-auto max-w-3xl space-y-8">
    <div><p className="font-mono text-[10px] tracking-[0.22em] text-muted-foreground">OWNER CONTROL / 03</p><h1 className="mt-2 text-3xl font-bold tracking-tight">إعدادات البوابة</h1><p className="mt-3 text-sm leading-7 text-muted-foreground">تحكّم في المساحات التي يراها أعضاء Strat. تغييراتك تُحفظ فوراً على هذا الجهاز.</p></div>
    <section className="rounded-2xl border border-border bg-card p-6 md:p-8">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-center"><span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-accent/35 text-[#735817]"><Gem className="size-6" /></span><div className="flex-1"><div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-bold">خدمات أسطورية</h2><span data-testid="status-visibility-badge" className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${visible ? 'bg-[#d6ebe4] text-[#2c7768]' : 'bg-muted text-muted-foreground'}`}>{visible ? 'ظاهرة للأعضاء' : 'مخفية عن الأعضاء'}</span></div><p className="mt-2 text-sm leading-6 text-muted-foreground">المساحة التي تجمع الجلسات والبرامج والتجارب الخاصة بالمجتمع.</p></div><button role="switch" aria-checked={visible} onClick={onToggle} data-testid="switch-services-visibility" className={`relative h-8 w-14 shrink-0 rounded-full p-1 transition-colors duration-300 ${visible ? 'bg-[#3d8b78]' : 'bg-muted-foreground/30'}`}><span className={`block size-6 rounded-full bg-card shadow-sm transition-transform duration-300 ${visible ? 'translate-x-0' : '-translate-x-6'}`} /></button></div>
      <div className="mt-7 border-t border-border pt-5"><p className="flex items-center gap-2 text-xs text-muted-foreground"><Check className="size-4 text-[#3d8b78]" /> الحالة محفوظة محلياً وتستمر بعد إعادة تحميل الصفحة</p></div>
    </section>
    <div className="rounded-2xl bg-primary p-6 text-primary-foreground"><div className="flex items-start gap-4"><Settings2 className="mt-0.5 size-5 text-accent" /><div><h3 className="font-bold">أنت تشاهدين المعاينة كمالك</h3><p className="mt-1 text-xs leading-6 text-primary-foreground/60">استخدمي زر تبديل الدور في القائمة الجانبية لمعاينة التجربة التي يراها العضو.</p></div></div></div>
  </div>;
}

function AccessDenied({ title, description, onBack }: { title: string; description: string; onBack: () => void }) {
  return <div className="mx-auto flex max-w-xl flex-col items-center justify-center py-20 text-center"><span className="grid size-16 place-items-center rounded-3xl bg-accent/30 text-[#735817]"><LockKeyhole className="size-7" /></span><h1 className="mt-7 text-2xl font-bold">{title}</h1><p className="mt-3 max-w-md text-sm leading-7 text-muted-foreground">{description}</p><button onClick={onBack} data-testid="button-access-denied-back" className="mt-7 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-bold text-primary-foreground transition-transform hover:-translate-y-0.5">العودة للرئيسية <ArrowLeft className="size-4" /></button></div>;
}

function Router({ role, setRole, servicesVisible, toggleServices }: { role: Role; setRole: (role: Role) => void; servicesVisible: boolean; toggleServices: () => void }) {
  return <AppShell role={role} setRole={setRole} servicesVisible={servicesVisible}><Switch><Route path="/" component={Home} /><Route path="/services"><Services visible={servicesVisible} /></Route><Route path="/owner-settings"><OwnerSettings role={role} visible={servicesVisible} onToggle={toggleServices} /></Route><Route component={NotFound} /></Switch></AppShell>;
}

function App() {
  const [role, setRole] = useState<Role>('member');
  const [servicesVisible, setServicesVisible] = useState(readServicesVisibility);
  useEffect(() => { try { window.localStorage.setItem(VISIBILITY_KEY, String(servicesVisible)); } catch { /* localStorage can be unavailable in private browsing */ } }, [servicesVisible]);
  const toggleServices = () => setServicesVisible((current) => !current);
  return <QueryClientProvider client={queryClient}><TooltipProvider><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><RoutedErrorBoundary><Router role={role} setRole={setRole} servicesVisible={servicesVisible} toggleServices={toggleServices} /></RoutedErrorBoundary></WouterRouter><Toaster /></TooltipProvider></QueryClientProvider>;
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

export default App;