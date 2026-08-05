import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, Router as WouterRouter } from 'wouter';

const queryClient = new QueryClient();

// Shared UI components to keep the design system consistent and self-contained
function CopyButton({ text, onClick }: { text?: string; onClick?: () => void }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (onClick) onClick();
    else if (text) navigator.clipboard.writeText(text);

    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      type="button"
      className="relative flex-shrink-0 flex items-center justify-center h-[42px] w-[64px] bg-primary text-primary-foreground font-bold rounded-md hover:bg-primary/90 transition-all focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 overflow-hidden shadow-sm"
    >
      <AnimatePresence mode="wait">
        {copied ? (
          <motion.span
            key="check"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex items-center justify-center text-xl font-sans"
          >
            ✓
          </motion.span>
        ) : (
          <motion.span
            key="copy"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex items-center justify-center text-sm font-sans"
          >
            نسخ
          </motion.span>
        )}
      </AnimatePresence>
    </button>
  );
}

function ActionButton({
  onClick,
  icon,
  label,
  variant = 'primary',
}: {
  onClick: () => void;
  icon?: string;
  label: string;
  variant?: 'primary' | 'destructive';
}) {
  const [done, setDone] = useState(false);

  const handleClick = () => {
    onClick();
    setDone(true);
    setTimeout(() => setDone(false), 2000);
  };

  const baseClass =
    'h-[42px] px-6 text-sm font-bold rounded-md transition-all flex items-center justify-center min-w-[140px] focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 overflow-hidden';
  const variants = {
    primary: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm',
    destructive: 'bg-destructive/10 text-destructive hover:bg-destructive/20',
  };

  return (
    <button onClick={handleClick} className={`${baseClass} ${variants[variant]}`}>
      <AnimatePresence mode="wait">
        {done ? (
          <motion.span
            key="check"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="text-xl font-sans"
          >
            ✓
          </motion.span>
        ) : (
          <motion.span
            key="label"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex items-center gap-2 font-sans"
          >
            {icon && <span className="text-base">{icon}</span>}
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </button>
  );
}

function Field({
  label,
  value,
  onChange,
  multiline = false,
  isMono = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  isMono?: boolean;
}) {
  const inputClass = `flex-1 w-full rounded-md border border-input bg-muted/30 px-3 py-2 text-[15px] shadow-sm placeholder:text-muted-foreground focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
    isMono ? 'font-mono text-left' : 'font-sans text-right'
  }`;

  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-bold text-foreground/90 mr-1">{label}</label>
      <div className="flex items-start gap-3">
        {multiline ? (
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            rows={4}
            dir="rtl"
            className={`${inputClass} resize-y min-h-[96px] leading-relaxed`}
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            dir={isMono ? 'ltr' : 'rtl'}
            className={`${inputClass} h-[42px]`}
          />
        )}
        <CopyButton text={value} />
      </div>
    </div>
  );
}

function Home() {
  const [id, setId] = useState('5957783780');
  const [email, setEmail] = useState('hdkdbdkdndkejj@gmail.com');
  const [password, setPassword] = useState('oetm t4sz 54cu 2my2 2j3j 2x4p 7t43 sqqo');
  const [message, setMessage] = useState('محمد');

  const handleCopyAll = () => {
    const text = `الأيدي: ${id}\nالإيميل: ${email}\nالباسورد: ${password}\nرسالة العضو: ${message}`;
    navigator.clipboard.writeText(text);
  };

  const handleClear = () => {
    setId('');
    setEmail('');
    setPassword('');
    setMessage('');
  };

  return (
    <div
      dir="rtl"
      className="min-h-[100dvh] w-full flex items-center justify-center bg-muted/40 p-4 md:p-8 font-sans selection:bg-primary/10"
    >
      <div className="w-full max-w-xl bg-card rounded-xl shadow-xl shadow-black/[0.03] border border-border/60 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-5 border-b border-border/60 bg-card">
          <h1 className="text-xl font-bold text-foreground">مراجعة بيانات العضو</h1>
          <p className="text-sm text-muted-foreground mt-1">
            تحقق من البيانات وانسخها للاعتماد
          </p>
        </div>

        {/* Content */}
        <div className="p-6 flex flex-col gap-5">
          <Field label="الأيدي" value={id} onChange={setId} isMono={true} />
          <Field label="الإيميل" value={email} onChange={setEmail} isMono={true} />
          <Field label="الباسورد" value={password} onChange={setPassword} isMono={true} />
          <Field
            label="رسالة العضو"
            value={message}
            onChange={setMessage}
            multiline={true}
          />
        </div>

        {/* Footer */}
        <div className="px-6 py-5 border-t border-border/60 bg-muted/10 flex items-center justify-between">
          <ActionButton onClick={handleClear} label="مسح الحقول" variant="destructive" />
          <ActionButton onClick={handleCopyAll} label="نسخ الكل" icon="📋" variant="primary" />
        </div>
      </div>
    </div>
  );
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={Home} />
      <Route>
        <div className="flex min-h-[100dvh] items-center justify-center font-sans">
          404 - Not Found
        </div>
      </Route>
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WouterRouter base={import.meta.env.BASE_URL?.replace(/\/$/, '') || ''}>
        <Router />
      </WouterRouter>
    </QueryClientProvider>
  );
}

export default App;
