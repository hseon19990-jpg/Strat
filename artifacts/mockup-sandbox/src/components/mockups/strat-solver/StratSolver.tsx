import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowDown,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  CircleHelp,
  Clipboard,
  Code2,
  Copy,
  GitBranch,
  Home,
  MoreVertical,
  Paperclip,
  Search,
  Send,
  SlidersHorizontal,
  Sparkles,
  SquareTerminal,
  Wrench,
} from "lucide-react";

type WorkRow = {
  title: string;
  body: string;
  time: string;
};

const workRows: WorkRow[] = [
  {
    title: "Worked for 43 seconds",
    time: "43s",
    body: "راجعت مسار التصويت بالكامل، وميّزت بين رابط المنشور نفسه ورابط القناة. النتيجة تشير إلى أن Bot B يحتاج إلى خطوة تحقق إضافية قبل تنفيذ التصويت.",
  },
  {
    title: "Investigating rake services",
    time: "1m",
    body: "أفحص الآن خدمة رشح التصويت وأين يتم إنشاء post_entity. سأرجع مسار التصويت نفسه لأننا نريد إحالة واضحة إلى Bot B، وليس إحالة داخلية للـ Railway.",
  },
  {
    title: "Proceeding with bot integration",
    time: "now",
    body: "فهمت التسلسل المطلوب الآن: الحساب ينضم للقناة الإلزامية، يرسل /start إلى Bot B، ينتظر التحقق، ثم يرسل رابط المنشور ويعيد نتيجة التصويت إلى المستخدم.",
  },
];

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative my-3 overflow-hidden rounded-lg border border-[#303034] bg-[#222225] text-left" dir="ltr">
      <button
        type="button"
        aria-label="Copy code"
        onClick={() => {
          void navigator.clipboard?.writeText(children);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }}
        className="absolute right-3 top-3 rounded-md p-1.5 text-[#929298] transition hover:bg-[#34343a] hover:text-[#e8e8eb]"
      >
        {copied ? <Check size={15} /> : <Copy size={15} />}
      </button>
      <pre className="whitespace-pre-wrap px-4 py-4 pr-12 font-mono text-[12px] leading-[1.7] text-[#d7d7dc]">
        {children}
      </pre>
    </div>
  );
}

function WorkStatus({ row, index }: { row: WorkRow; index: number }) {
  const [open, setOpen] = useState(index === 2);
  return (
    <div className="my-4 rounded-lg border border-[#29292d] bg-[#202023]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-3 py-3 text-left"
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-[#39393e] bg-[#29292d] text-[#a9a9b0]">
          {index === 2 ? <GitBranch size={14} /> : <Sparkles size={14} />}
        </span>
        <span className="flex-1 text-[13px] font-medium text-[#b9b9bf]">{row.title}</span>
        <span className="text-[11px] text-[#68686e]">{row.time}</span>
        {open ? <ChevronUp size={15} className="text-[#8a8a91]" /> : <ChevronDown size={15} className="text-[#8a8a91]" />}
      </button>
      {open && <div className="border-t border-[#303034] px-4 pb-4 pt-3 text-right text-[13px] leading-7 text-[#c5c5c9]" dir="rtl">{row.body}</div>}
    </div>
  );
}

export function StratSolver() {
  const [activeNav, setActiveNav] = useState("home");
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Array<{ text: string; assistant?: boolean }>>([]);
  const threadRef = useRef<HTMLDivElement>(null);

  const scrollLatest = () => threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  const sendMessage = (event: FormEvent) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setMessages((items) => [...items, { text: value }, { assistant: true, text: "أفحص الطلب داخل المسار الحالي… سأتحقق من Railway و Bot B ثم أرجع بخطوة عملية قصيرة." }]);
    setDraft("");
    window.setTimeout(scrollLatest, 40);
  };

  useEffect(() => {
    const element = threadRef.current;
    if (!element) return;
    const onScroll = () => setExpanded(element.scrollHeight - element.scrollTop - element.clientHeight < 100);
    element.addEventListener("scroll", onScroll);
    return () => element.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="min-h-[100dvh] w-full bg-[#111112] text-[#e8e8e9]">
      <style>{`
        .strat-scroll::-webkit-scrollbar{width:5px}.strat-scroll::-webkit-scrollbar-thumb{background:#5a5a5e;border-radius:10px}
        .strat-fade{background:linear-gradient(180deg,rgba(17,17,18,0),#111112 88%)}
        @media (min-width: 640px){.strat-shell{box-shadow:0 0 0 1px #29292d,0 24px 80px rgba(0,0,0,.5);}}
      `}</style>
      <main className="strat-shell relative mx-auto flex min-h-[100dvh] max-w-[430px] flex-col overflow-hidden bg-[#171718]">
        <header className="z-20 flex shrink-0 items-center gap-2 border-b border-[#27272a] bg-[#171718] px-3 py-3">
          <button type="button" aria-label="Go back" className="rounded-md p-2 text-[#c7c7cb] hover:bg-[#29292d]"><ArrowLeft size={19} /></button>
          <button type="button" className="flex h-10 flex-1 items-center justify-between rounded-xl border border-[#37373b] bg-[#29292c] px-3 shadow-inner shadow-black/15">
            <span className="flex items-center gap-2 text-[14px] font-semibold"><SquareTerminal size={16} className="text-[#e1e1e5]" /> Strat Solver</span><ChevronDown size={16} className="text-[#9a9a9f]" />
          </button>
          <button type="button" aria-label="Tools" className="grid h-10 w-12 place-items-center rounded-xl border border-[#303034] bg-[#242426] text-[#7c7c82] hover:text-[#d2d2d6]"><Wrench size={17} /></button>
          <button type="button" aria-label="Controls" className="grid h-10 w-12 place-items-center rounded-xl border border-[#303034] bg-[#242426] text-[#7c7c82] hover:text-[#d2d2d6]"><SlidersHorizontal size={17} /></button>
        </header>

        <section ref={threadRef} className="strat-scroll relative flex-1 overflow-y-auto px-5 pb-44 pt-5">
          <div className="mb-4 flex items-center justify-between text-[11px] text-[#65656b]">
            <span className="flex items-center gap-1.5"><CircleHelp size={13} /> Investigation thread</span>
            <span className="font-mono">private / active</span>
          </div>
          <article dir="rtl" className="text-right text-[14px] leading-[2] text-[#dedee1]">
            <p>المفتاح غير موجود في Railway. إذا ظهر <span dir="ltr" className="font-mono text-[#bdbdc4]">401</span> فالمفتاح غير صحيح، وإذا ظهر <span dir="ltr" className="font-mono text-[#bdbdc4]">404</span> أو <span dir="ltr" className="font-mono text-[#bdbdc4]">model_decommissioned</span> فالموديل قديم.</p>
            <p className="mt-3">الأفضل استخدام حسابات اختبار مضافة إلى <strong className="font-semibold text-[#f0f0f2]">Bot B</strong> الآن على قائمة الأمان، ثم تعطيل التحقق في وضع الاختبار بدل جعل الحسابات تتجاوز تحققاً حقيقياً آلياً.</p>
            <WorkStatus row={workRows[0]} index={0} />
            <div className="my-4 ml-auto max-w-[86%] rounded-2xl rounded-br-sm bg-[#17477a] px-4 py-3 text-right text-[14px] leading-7 text-[#e4efff]" dir="rtl">
              أكلم عن خدمات الرشق — رشق تصويت يتحقق من القناة الإحالة وليس مجرد فحص الرابط.
            </div>
            <div className="mb-5 text-left text-[11px] text-[#77777e]" dir="ltr">Just now <span className="ml-2">⋮⋮</span></div>
            <WorkStatus row={workRows[1]} index={1} />
            <p>تمام، نقصد خدمة خدمات الرشق ← رشق تصويت يتحقق، وليس إحالات <span dir="ltr" className="font-mono">Bot B</span> مباشرة. سأراجع مسار التصويت نفسه لأن له كوداً منفصلاً عن <span dir="ltr" className="font-mono">referrals.py</span>.</p>
            <div className="my-3 flex items-center gap-1 text-[#88888f]" dir="ltr">
              <button type="button" aria-label="Copy" className="rounded-md border border-[#343438] bg-[#222225] p-2 hover:text-white"><Copy size={14} /></button>
              <button type="button" aria-label="Open code" className="rounded-md border border-[#343438] bg-[#222225] p-2 hover:text-white"><Code2 size={14} /></button>
              <span className="ml-2 text-[11px]">8 actions</span>
            </div>
            <p className="mt-4">الآن اتضح المقصود. سبب المشكلة الأساسي أن <span dir="ltr" className="font-mono">_execute_votes_ai</span> يتعامل مع رابط المنشور كأنه هو مكان التحقق:</p>
            <CodeBlock>{`post_entity = await
client.get_entity(post_ref)
...
messages = await
client.get_messages(post_entity, limit=15)
solved, detail = await
solve_captcha_with_ai(
    client, post_entity, messages, ...
)`}</CodeBlock>
            <p>لا يرى Groq رسالة التحقق أصلاً حتى لو كان <span dir="ltr" className="font-mono">GROQ_API_KEY</span> صحيحاً. توجد أيضاً احتمالية ثانوية:</p>
            <ul className="my-2 list-disc space-y-1 pr-5">
              <li>قديمة، خصوصاً موديل الرؤية Groq الذي يستخدم موديلات <span dir="ltr" className="font-mono">llama-3.2-90b-vision-preview</span>.</li>
              <li>إذا ظهر في السجل <span dir="ltr" className="font-mono">404</span> أو <span dir="ltr" className="font-mono">model_decommissioned</span> فالمشكلة من اسم الموديل.</li>
            </ul>
            <CodeBlock>{`GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"`}</CodeBlock>
            <p>الحل الآمن هو إضافة وضع اختبار أو قائمة حسابات مسموحة في Railway، ثم نربط الحسابات بقناة Bot B قبل تفعيل التصويت.</p>
            <WorkStatus row={workRows[2]} index={2} />
            {messages.map((message, index) => message.assistant ? <div key={index} className="my-4 rounded-xl border border-[#2e343d] bg-[#1d252e] px-4 py-3 text-right text-[13px] leading-7 text-[#cbd9e8]">{message.text}</div> : <div key={index} className="my-4 ml-auto max-w-[88%] rounded-2xl rounded-br-sm bg-[#17477a] px-4 py-3 text-right text-[14px] leading-7 text-[#e4efff]">{message.text}</div>)}
          </article>
        </section>

        <div className="pointer-events-none absolute bottom-[116px] left-1/2 z-30 w-full max-w-[430px] -translate-x-1/2">
          {!expanded && <button type="button" onClick={scrollLatest} className="pointer-events-auto mx-auto flex items-center gap-2 rounded-full border border-[#45454a] bg-[#252528] px-3 py-2 text-[12px] text-[#d6d6da] shadow-xl shadow-black/30"><ArrowDown size={14} /> Scroll to latest</button>}
        </div>
        <form onSubmit={sendMessage} className="absolute bottom-[58px] left-1/2 z-20 w-full max-w-[430px] -translate-x-1/2 border-t border-[#27272a] bg-[#171718]/95 px-4 pb-3 pt-3 backdrop-blur">
          <div className="flex items-center gap-2 rounded-xl border border-[#37373b] bg-[#242426] px-3 py-1.5">
            <button type="button" aria-label="Attach" className="text-[#818188] hover:text-[#d5d5d8]"><Paperclip size={17} /></button>
            <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Make lightweight changes, quickly..." className="min-w-0 flex-1 bg-transparent py-2 text-[13px] text-[#eeeeef] outline-none placeholder:text-[#77777d]" />
            <button type="submit" aria-label="Send" className="rounded-lg bg-[#2d68a2] p-2 text-white transition hover:bg-[#397bb8]"><Send size={15} /></button>
          </div>
        </form>
        <nav className="z-30 flex h-[58px] shrink-0 items-center justify-around border-t border-[#28282b] bg-[#111112] text-[#707076]">
          {[{ key: "home", Icon: Home }, { key: "saved", Icon: BookOpen }, { key: "search", Icon: Search }, { key: "canvas", Icon: Clipboard }, { key: "more", Icon: MoreVertical }].map(({ key, Icon }) => {
            return <button type="button" key={key} onClick={() => setActiveNav(key)} className={`flex h-full w-16 flex-col items-center justify-center gap-1 transition ${activeNav === key ? "text-[#f0f0f2]" : "hover:text-[#b7b7bc]"}`}><Icon size={20} strokeWidth={activeNav === key ? 2.2 : 1.8} /><span className="text-[9px] capitalize">{key}</span></button>;
          })}
        </nav>
      </main>
    </div>
  );
}