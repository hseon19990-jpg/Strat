import { useState } from "react";
import { Check, ChevronLeft, MoreVertical, Paperclip, Send, Smile } from "lucide-react";

const defaultThankYou = "شكراً لك على مساعدتي وإتمام التحقق.";

export function ThankYou() {
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [message, setMessage] = useState(defaultThankYou);
  const [sentMessage, setSentMessage] = useState<string | null>(null);

  function handleSend() {
    const trimmed = message.trim();
    if (!trimmed) return;

    setSentMessage(trimmed);
    setIsComposerOpen(false);
    setMessage(defaultThankYou);
  }

  return (
    <main
      dir="rtl"
      className="min-h-screen bg-[#d9f1c8] text-[#202124] [font-family:Arial,'Noto Sans Arabic',sans-serif]"
      style={{
        backgroundImage:
          "linear-gradient(rgba(218,240,202,.86),rgba(218,240,202,.86)), radial-gradient(circle at 20px 20px, rgba(103,145,85,.12) 2px, transparent 2.5px)",
        backgroundSize: "auto, 42px 42px",
      }}
    >
      <header className="sticky top-0 z-10 flex h-[70px] items-center gap-3 bg-[#78a947] px-3 text-white shadow-sm">
        <button
          aria-label="رجوع"
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-[#334229] shadow-sm transition-transform active:scale-95"
        >
          <ChevronLeft className="h-6 w-6 rotate-180" />
        </button>
        <div className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full border-2 border-white/80 bg-[#263f55] text-xl shadow">
          🪐
        </div>
        <div className="min-w-0 flex-1 text-right">
          <h1 className="truncate text-[18px] font-bold">ارتشفلي / Arshaqli</h1>
          <p className="text-[12px] text-white/85">بوت التحقق والنقاط</p>
        </div>
        <button aria-label="المزيد" className="grid h-10 w-10 place-items-center rounded-full transition-colors hover:bg-white/10">
          <MoreVertical className="h-5 w-5" />
        </button>
      </header>

      <section className="mx-auto flex min-h-[calc(100vh-70px)] w-full max-w-[460px] flex-col justify-end gap-3 px-3 pb-5 pt-6">
        <div className="self-center rounded-full bg-[#c3dea9] px-4 py-1 text-[11px] font-semibold text-[#4b6840] shadow-sm">
          اليوم
        </div>

        <div className="max-w-[92%] self-start rounded-2xl rounded-tr-md bg-white px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,.12)]">
          <p className="mb-1 text-[15px] font-medium leading-7">
            تم التحقق من طلبك بنجاح ✅
          </p>
          <p className="text-[14px] leading-7 text-[#454545]">
            شكراً لتعاونك. ستتم إضافة النقاط إلى حسابك قريباً.
          </p>
          <span className="mt-1 block text-left text-[10px] text-gray-400">5:23 م</span>
        </div>

        <div className="max-w-[92%] self-start rounded-2xl rounded-tr-md bg-white px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,.12)]">
          <p className="text-[14px] leading-7 text-[#454545]">
            إذا أردت، يمكنك إرسال رسالة شكر قصيرة إلى مالك البوت.
          </p>
          <span className="mt-1 block text-left text-[10px] text-gray-400">5:24 م</span>
        </div>

        {sentMessage && (
          <div className="max-w-[86%] self-end rounded-2xl rounded-tl-md bg-[#e8ffd5] px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,.12)]">
            <p className="text-[14px] leading-7">{sentMessage}</p>
            <div className="mt-1 flex items-center justify-end gap-1 text-[10px] text-gray-400">
              <span>5:25 م</span>
              <Check className="h-3.5 w-3.5 text-[#40a85a]" />
              <Check className="-mr-2.5 h-3.5 w-3.5 text-[#40a85a]" />
            </div>
          </div>
        )}

        {!isComposerOpen && (
          <button
            type="button"
            onClick={() => setIsComposerOpen(true)}
            className="mt-1 flex w-full items-center justify-center gap-2 rounded-2xl bg-[#71a346] px-5 py-3.5 text-[15px] font-bold text-white shadow-[0_3px_0_rgba(63,103,45,.4)] transition-all hover:bg-[#638f3d] active:translate-y-0.5 active:shadow-none"
          >
            <span aria-hidden="true">💌</span>
            إرسال رسالة شكر للمالك
          </button>
        )}

        {isComposerOpen && (
          <div className="rounded-2xl border border-[#b7d79d] bg-white p-3 shadow-[0_4px_15px_rgba(56,91,42,.16)]">
            <label htmlFor="thank-you-message" className="mb-2 block text-right text-[13px] font-bold text-[#405b36]">
              اكتب رسالة الشكر
            </label>
            <textarea
              id="thank-you-message"
              autoFocus
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={3}
              maxLength={240}
              placeholder="اكتب رسالتك هنا..."
              className="w-full resize-none rounded-xl border border-[#d5e6ca] bg-[#fbfdf9] px-3 py-2 text-right text-[14px] leading-6 outline-none transition focus:border-[#78a947] focus:ring-2 focus:ring-[#78a947]/20"
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => {
                  setIsComposerOpen(false);
                  setMessage(defaultThankYou);
                }}
                className="rounded-xl px-4 py-2 text-[13px] font-semibold text-[#70806a] transition hover:bg-[#f0f6ec]"
              >
                إلغاء
              </button>
              <button
                type="button"
                onClick={handleSend}
                disabled={!message.trim()}
                className="flex items-center gap-2 rounded-xl bg-[#71a346] px-5 py-2 text-[13px] font-bold text-white transition hover:bg-[#638f3d] disabled:cursor-not-allowed disabled:opacity-45"
              >
                إرسال
                <Send className="h-4 w-4 rotate-180" />
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 rounded-full bg-white px-3 py-2 text-gray-400 shadow-[0_1px_3px_rgba(0,0,0,.12)]">
          <button aria-label="إرفاق ملف" className="p-1">
            <Paperclip className="h-5 w-5" />
          </button>
          <span className="flex-1 text-right text-[14px]">الرسالة</span>
          <button aria-label="إضافة رمز تعبيري" className="p-1">
            <Smile className="h-5 w-5" />
          </button>
          <div className="grid h-9 w-9 place-items-center rounded-full bg-[#2b9bdd] text-white">
            <Send className="h-4 w-4 rotate-180" />
          </div>
        </div>
      </section>
    </main>
  );
}