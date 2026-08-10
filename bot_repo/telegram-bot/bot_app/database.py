"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 20, DATABASE_URL,
                    connect_timeout=10
                )
    return _pool

def reset_pool():
    """إعادة تهيئة pool الاتصالات عند حدوث خطأ فادح"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
    logger.warning("⚠️ تم إعادة تهيئة pool قاعدة البيانات")

class SmartCursor:
    """Wrapper يحوّل ? إلى %s ويعيد نفسه من execute() لدعم السلسلة .fetchone()"""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        if params is None:
            self._cur.execute(sql)
        else:
            self._cur.execute(sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __iter__(self):
        return iter(self._cur)

_DB_RETRY_EXC = (psycopg2.OperationalError, psycopg2.InterfaceError)

class _DBContext:
    """
    مدير سياق آمن لاتصالات PostgreSQL.
    - يختبر الاتصال عند الاستحواذ ويعيد المحاولة مرة واحدة بعد reset_pool.
    - يعيد المحاولة في __exit__ عند فشل commit بسبب انقطاع الشبكة.
    - يُرجع الاتصال المكسور دائماً بـ close=True حتى لا يعود إلى الـ pool.
    """
    def __enter__(self):
        self._conn = None
        self._pool = None
        for attempt in range(2):
            try:
                self._pool = get_pool()
                self._conn = self._pool.getconn()
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                break
            except _DB_RETRY_EXC as e:
                if attempt == 0:
                    logger.warning(f"⚠️ خطأ في الاتصال بالDB، إعادة المحاولة... ({e})")
                    if self._conn is not None and self._pool is not None:
                        try:
                            self._pool.putconn(self._conn, close=True)
                        except Exception:
                            pass
                        self._conn = None
                    reset_pool()
                else:
                    raise
        self._raw = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return SmartCursor(self._raw)

    def __exit__(self, exc_type, exc_val, exc_tb):
        conn_broken = False
        try:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        except _DB_RETRY_EXC as e:
            logger.warning(f"⚠️ فشل commit/rollback: {e}")
            conn_broken = True
            try:
                self._conn.rollback()
            except Exception:
                pass
        finally:
            try:
                self._raw.close()
            except Exception:
                pass
            if self._conn is not None and self._pool is not None:
                try:
                    self._pool.putconn(self._conn, close=conn_broken)
                except Exception:
                    pass
        return False

def db_conn():
    return _DBContext()

def with_db_retry(fn, *args, **kwargs):
    """
    تشغيل دالة تستخدم db_conn مع إعادة محاولة واحدة عند انقطاع الاتصال.
    مفيد لعمليات الكتابة الحساسة مثل set_setting.
    """
    for attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except _DB_RETRY_EXC as e:
            if attempt == 0:
                logger.warning(f"⚠️ إعادة محاولة بعد خطأ DB: {e}")
                reset_pool()
            else:
                raise

def init_db():
      logger.info(f"🐘 PostgreSQL DB | DATABASE_URL configured: {bool(DATABASE_URL)}")
      with db_conn() as c:
          c.execute("""
          CREATE TABLE IF NOT EXISTS users (
              user_id      BIGINT PRIMARY KEY,
              username     TEXT,
              full_name    TEXT,
              points       INTEGER DEFAULT 0,
              invited_by   BIGINT DEFAULT 0,
              total_orders INTEGER DEFAULT 0,
              joined_at    TEXT DEFAULT CURRENT_DATE,
              bot_user_num INTEGER,
              verified     INTEGER DEFAULT 0
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS orders (
              id           SERIAL PRIMARY KEY,
              user_id      BIGINT,
              service_id   INTEGER,
              link         TEXT,
              quantity     INTEGER,
              cost_points  INTEGER DEFAULT 0,
              cost_stars   INTEGER DEFAULT 0,
              api_order_id TEXT DEFAULT '',
              status       TEXT DEFAULT 'pending',
              order_code   TEXT,
              created_at   TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS services (
              id              SERIAL PRIMARY KEY,
              category        TEXT,
              api_service_id  INTEGER,
              panel           INTEGER DEFAULT 1,
              name_ar         TEXT,
              description     TEXT,
              min_qty         INTEGER,
              max_qty         INTEGER,
              price_per_point REAL,
              active          INTEGER DEFAULT 1,
              service_type    TEXT DEFAULT 'smm'
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_sub_orders (
              id            SERIAL PRIMARY KEY,
              user_id       BIGINT NOT NULL,
              bot_username  TEXT NOT NULL,
              start_param   TEXT NOT NULL,
              channels      TEXT DEFAULT '',
              quantity      INTEGER NOT NULL,
              cost_points   INTEGER NOT NULL,
              done_count    INTEGER DEFAULT 0,
              failed_count  INTEGER DEFAULT 0,
              status        TEXT DEFAULT 'pending',
              order_code    TEXT,
              created_at    TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS forced_ref_orders (
              id            SERIAL PRIMARY KEY,
              user_id       BIGINT NOT NULL,
              bot_username  TEXT NOT NULL,
              start_param   TEXT NOT NULL,
              channels      TEXT DEFAULT '',
              quantity      INTEGER NOT NULL,
              cost_points   INTEGER NOT NULL,
              done_count    INTEGER DEFAULT 0,
              failed_count  INTEGER DEFAULT 0,
              status        TEXT DEFAULT 'pending',
              order_code    TEXT,
              created_at    TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS settings (
              key   TEXT PRIMARY KEY,
              value TEXT
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS account_media_assignments (
              id           SERIAL PRIMARY KEY,
              kind         TEXT NOT NULL CHECK (kind IN ('stories', 'avatar')),
              stock_id     INTEGER NOT NULL,
              phone_number TEXT,
              status       TEXT NOT NULL DEFAULT 'processing'
                           CHECK (status IN ('processing', 'completed')),
              assigned_at  TIMESTAMPTZ DEFAULT NOW(),
              completed_at TIMESTAMPTZ,
              UNIQUE (kind, stock_id)
          )""")
          c.execute("""
          CREATE UNIQUE INDEX IF NOT EXISTS account_media_assignments_kind_phone_uq
          ON account_media_assignments (kind, phone_number)
          WHERE phone_number IS NOT NULL AND BTRIM(phone_number) <> ''
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS account_name_assignments (
              phone_number  TEXT PRIMARY KEY,
              assigned_name TEXT NOT NULL,
              assigned_at   TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS daily_gifts (
              user_id    BIGINT PRIMARY KEY,
              last_claim TEXT
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_funding (
              id               SERIAL PRIMARY KEY,
              user_id          BIGINT,
              channel_username TEXT,
              funding_type     TEXT,
              cost_points      INTEGER,
              active           INTEGER DEFAULT 1,
              created_at       TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS star_transactions (
              id                  SERIAL PRIMARY KEY,
              user_id             BIGINT,
              stars               INTEGER,
              points_given        INTEGER,
              telegram_payment_id TEXT,
              status              TEXT DEFAULT 'completed',
              created_at          TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_star_purchases (
              telegram_payment_id TEXT PRIMARY KEY,
              user_id             BIGINT NOT NULL,
              stars               INTEGER NOT NULL,
              phone_number        TEXT,
              status              TEXT DEFAULT 'pending',
              created_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS point_transfers (
              id         SERIAL PRIMARY KEY,
              from_user  BIGINT,
              to_user    BIGINT,
              points     INTEGER,
              fee        INTEGER,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS prize_exchanges (
              id          SERIAL PRIMARY KEY,
              user_id     BIGINT,
              prize_type  TEXT,
              prize_value TEXT,
              points_cost INTEGER,
              status      TEXT DEFAULT 'pending',
              created_at  TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_stock (
              id            SERIAL PRIMARY KEY,
              phone_number  TEXT UNIQUE,
              assigned_to   BIGINT,
              assigned_at   TIMESTAMPTZ,
              added_at      TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_channels (
              id               SERIAL PRIMARY KEY,
              channel_username TEXT UNIQUE,
              channel_title    TEXT,
              owner_user_id    BIGINT DEFAULT 0,
              funding_type     TEXT DEFAULT 'mandatory',
              active           INTEGER DEFAULT 1
          )""")
          for _alt in [
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS target_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS current_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS queued INTEGER DEFAULT 0",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS order_code TEXT",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS owner_seen BOOLEAN DEFAULT FALSE",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_at TIMESTAMPTZ",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_pts INTEGER DEFAULT 0",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_reason TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS ever_sold BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS session_string TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS sessions_reset BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS force_listed BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS frozen_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS twofa_password TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_frozen BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_authorized BOOLEAN DEFAULT TRUE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS last_device_count INTEGER DEFAULT -1",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS kicked_at TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS auto_2fa_enabled BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS twofa_reset_date TIMESTAMPTZ",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS is_solo BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS can_send_code BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS bot_session_ip TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS forced_ref_excluded BOOLEAN DEFAULT FALSE",
              "ALTER TABLE services ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'tg'",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned INTEGER DEFAULT 0",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMPTZ",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
              "ALTER TABLE channel_join_rewards ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW()",
              "ALTER TABLE mandatory_sub_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS referral_only BOOLEAN DEFAULT FALSE",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'points'",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS cost_stars INTEGER DEFAULT 0",
          ]:
              try: c.execute(_alt)
              except Exception: pass
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_funding_counts (
              id         SERIAL PRIMARY KEY,
              user_id    BIGINT NOT NULL,
              funding_id INTEGER NOT NULL,
              UNIQUE(user_id, funding_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS custom_prizes (
              id          SERIAL PRIMARY KEY,
              name        TEXT NOT NULL,
              quantity    INTEGER DEFAULT 1,
              points_cost INTEGER NOT NULL,
              active      INTEGER DEFAULT 1,
              created_at  TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS promo_codes (
              code       TEXT PRIMARY KEY,
              max_uses   INTEGER DEFAULT 1,
              used_count INTEGER DEFAULT 0,
              points     INTEGER DEFAULT 0,
              active     INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS promo_uses (
              code    TEXT,
              user_id BIGINT,
              used_at TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (code, user_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_purchase_codes (
              code       TEXT PRIMARY KEY,
              max_uses   INTEGER DEFAULT 1,
              used_count INTEGER DEFAULT 0,
              active     INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_purchase_code_uses (
              code    TEXT,
              user_id BIGINT,
              used_at TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (code, user_id)
          )""")
          try:
              c.execute("ALTER TABLE promo_uses ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ DEFAULT NOW()")
          except Exception:
              pass
          c.execute("""
          CREATE TABLE IF NOT EXISTS exchange_star_packages (
              id     SERIAL PRIMARY KEY,
              stars  INTEGER NOT NULL,
              active INTEGER DEFAULT 1
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_join_rewards (
              user_id    BIGINT,
              channel_id BIGINT,
              joined_at  TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, channel_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_tasks (
              id                  SERIAL PRIMARY KEY,
              label               TEXT NOT NULL,
              bot_username        TEXT NOT NULL,
              start_param         TEXT NOT NULL,
              mandatory_channels  TEXT DEFAULT '',
              folder_link         TEXT DEFAULT '',
              active              INTEGER DEFAULT 1,
              created_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_completions (
              task_id   INTEGER NOT NULL,
              stock_id  INTEGER NOT NULL,
              status    TEXT DEFAULT 'pending',
              done_at   TIMESTAMPTZ,
              error_msg TEXT,
              PRIMARY KEY (task_id, stock_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS supervisors (
              id         SERIAL PRIMARY KEY,
              user_id    BIGINT UNIQUE NOT NULL,
              username   TEXT DEFAULT '',
              added_at   TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS supervisor_accounts (
              id             SERIAL PRIMARY KEY,
              supervisor_id  BIGINT NOT NULL,
              phone_number   TEXT NOT NULL,
              session_string TEXT,
              added_at       TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE(supervisor_id, phone_number)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS gmail_submissions (
              id          SERIAL PRIMARY KEY,
              user_id     BIGINT NOT NULL,
              gmail_email TEXT NOT NULL,
              gmail_pass  TEXT NOT NULL,
              verification_note TEXT DEFAULT '',
              status      TEXT DEFAULT 'pending',
              created_at  TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS menu_items (
              id           SERIAL PRIMARY KEY,
              menu         TEXT,
              label        TEXT,
              action_type  TEXT DEFAULT 'builtin',
              action_value TEXT,
              width        INTEGER DEFAULT 2,
              sort_order   INTEGER DEFAULT 0,
              enabled      INTEGER DEFAULT 1
          )""")
          default_settings = [
              ('join_channel_reward', '45'),
              ('daily_gift_points', '50'),
              ('referral_points', '30'),
              ('star_to_points', '250'),
              ('exchange_star_rate', '2000'),
              ('telegram_number_cost', '5000'),
              ('telegram_number_stars', '18'),
              ('transfer_fee_percent', '1'),
              ('mandatory_channel_cost', '200'),
              ('internal_channel_cost', '100'),
              ('welcome_message', 'أهلاً وسهلاً بك في البوت!'),
              ('owner_contact', ''),
              ('total_bot_orders', '0'),
              ('total_bot_users', '0'),
              ('asiacell_text', '⚠️ الشحن التلقائي عبر اسيا سيل غير متاح حالياً.\nيرجى التواصل مع المالك.'),
              ('captcha_enabled', '0'),
              ('maintenance_mode', '0'),
              ('number_exchange_enabled', '0'),
              ('legendary_services_visible', '1'),
              ('exchange_success_msg', ''),
              ('mandatory_channel_min_members', '0'),
              ('internal_channel_min_members', '0'),
              ('owner_contact_label', '💬 تواصل مع المالك'),
              ('support_contact_label', '🛎 تواصل مع الدعم'),
              ('thank_owner_button_label', '💌 شكر المالك'),
              ('thank_owner_ar_button_label', '🇸🇦 رسالة بالعربية'),
              ('thank_owner_en_button_label', '🇬🇧 Message in English'),
              ('thank_owner_photo_button_label', '🖼️ إرسال صورة'),
              ('thank_owner_ar_prompt', '💌 أرسل رسالة الشكر بالعربية:'),
              ('thank_owner_en_prompt', '💌 Send your thank-you message in English:'),
              ('thank_owner_photo_prompt', '🖼️ أرسل الصورة التي تريد مشاركتها مع المالك:'),
              ('thank_owner_success_message', '✅ تم إرسال شكرك إلى المالك، شكراً لك!'),
              ('channel_leave_penalty', '75'),
              ('mandatory_stars_min_members', '50'),
              ('mandatory_stars_tier1_max', '120'),
              ('mandatory_stars_tier1_price_x100', '50'),   # 0.50 نجمة × 100
                            ('mandatory_stars_tier2_price_x100', '33'),   # 0.33 نجمة × 100
              ('mandatory_points_price', '5'),    # سعر العضو الواحد بالنقاط
              ('mandatory_points_min',   '50'),   # الحد الأدنى للأعضاء
              ('mansub_base_price',    '250'),
              ('mansub_channel_price', '50'),
              ('mansub_visible',       '0'),
              ('forced_ref_base_price',         '250'),   # سعر الإحالة بدون تحقق (نقاط/حساب)
              ('forced_ref_ai_base_price',      '300'),   # سعر الإحالة بتحقق (نقاط/حساب)
              ('forced_ref_channel_price',      '25'),    # سعر القناة (نقاط/قناة) — للنوعين
              ('forced_ref_channel_stars_no_ai','25'),    # سعر القناة بالنجوم — بدون تحقق
              ('forced_ref_channel_stars_ai',   '35'),    # سعر القناة بالنجوم — بتحقق
              ('forced_ref_visible',            '0'),
              ('forced_ref_ai_visible',         '0'),
              ('referral_task_delay',            '30'),  # تأخير بين الحسابات في مهام الإحالة (ثوانٍ)
              ('internal_leave_grace_hours', '24'),
              ('gmail_points_reward', '10000'),
              ('gmail_intro_message', 'للحصول على النقاط يجب عليك تقديم حساب جيميل لا تستخدمه، سيتم مراجعته من قبل المالك وإضافة النقاط بعد التحقق.'),
              ('gmail_button_label', '📧 احصل على نقاط مقابل إيميل جيميل'),
              ('gmail_email_prompt', '📧 *أرسل الإيميل*\n\nأرسل عنوان البريد الإلكتروني فقط بدون أي شيء آخر:'),
              ('gmail_password_prompt', '🔐 *أرسل الباسورد*\n\nأرسل كلمة مرور الحساب فقط بدون أي شيء آخر:'),
              ('gmail_verification_note_prompt', '💬 <b>اكتب رسالتك للمالك</b>\n\nيجب كتابة ملاحظة قبل إرسال إشعار إكمال التحقق.'),
              ('gmail_logout_instructions', '🔒 <b>خطوة مهمة لحماية حسابك</b>\n\nبعد إرسال الملاحظة، سجّل الخروج من حساب Google:\n\n1. افتح Gmail أو حساب Google.\n2. اضغط على صورة الحساب.\n3. اختر <b>تسجيل الخروج</b>.\n4. إذا كنت تستخدم جهازاً مشتركاً، افتح إدارة حساب Google ثم قسم الأمان، وراجع الأجهزة المسجّل دخولها وأزل الجهاز عند الحاجة.'),
              ('gmail_reject_wrong_email_msg', '❌ تم رفض طلبك بسبب أن الإيميل الذي أرسلته خاطئ أو غير صحيح. يرجى التحقق من الإيميل والمحاولة مجدداً.'),
              ('gmail_reject_wrong_pass_caption', '❌ تم رفض طلبك بسبب أن كلمة المرور خاطئة. شاهد الفيديو التالي لمعرفة كيفية إدخال الباسورد الصحيح.'),
              ('gmail_reject_wrong_pass_video', ''),
              ('gmail_reject_need_verify_caption', '❌ تم رفض طلبك لأن الحساب يحتاج إلى تحقق. شاهد الفيديو التالي لمعرفة كيفية إتمام التحقق.'),
              ('gmail_reject_need_verify_video', ''),
          ]
          for k, v in default_settings:
              c.execute(
                  "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                  (k, v)
              )
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS rejection_reason TEXT DEFAULT ''"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_completed BOOLEAN DEFAULT FALSE"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_notified BOOLEAN DEFAULT FALSE"
              )
              c.execute(
                  "ALTER TABLE gmail_submissions "
                  "ADD COLUMN IF NOT EXISTS verification_note TEXT DEFAULT ''"
              )
      except Exception as e:
          logger.warning(f"⚠️ فشل تحديث أعمدة تحقق الإيميل: {e}")
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE services ADD COLUMN panel INTEGER DEFAULT 1")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
              c.execute("UPDATE users SET referral_credited=1 WHERE invited_by IS NOT NULL AND invited_by != 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS partial_refund_pts INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_points_blocked INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credited_at TIMESTAMPTZ")
              c.execute(
                  "UPDATE users SET credited_at=joined_at::timestamptz "
                  "WHERE referral_credited=1 AND credited_at IS NULL"
              )
      except Exception as e:
          logger.warning(f"⚠️ فشل تعبئة credited_at للدعوات القديمة: {e}")
      try:
          with db_conn() as c:
              fixed = c.execute(
                  "UPDATE mandatory_channels SET funding_type='mandatory' "
                  "WHERE funding_type='mandatory_points'"
              ).rowcount
          if fixed:
              logger.info(f"✅ تم تصحيح {fixed} قناة إجبارية كانت مخزّنة بـ mandatory_points → mandatory")
      except Exception as e:
          logger.warning(f"⚠️ فشل تصحيح القنوات الإجبارية القديمة: {e}")

      try:
          with db_conn() as c:
              c.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS service_type TEXT DEFAULT 'smm'")
      except Exception: pass
      try:
          with db_conn() as c:
              if not c.execute("SELECT id FROM services WHERE service_type='mandatory_sub' LIMIT 1").fetchone():
                  c.execute(
                      "INSERT INTO services (category,api_service_id,panel,platform,name_ar,description,min_qty,max_qty,price_per_point,active,service_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      ('start_bot',0,0,'tg','🔑 الاشتراك الإجباري','حسابات المخزون تنضم لقنواتك ثم تضغط ستارت',1,9999,0,1,'mandatory_sub')
                  )
      except Exception as _e: logger.warning(f'mansub seed: {_e}')
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE referral_tasks ADD COLUMN IF NOT EXISTS mandatory_channels TEXT DEFAULT ''")
              c.execute("ALTER TABLE referral_tasks ADD COLUMN IF NOT EXISTS folder_link TEXT DEFAULT ''")
      except Exception:
          pass

      try:
          with db_conn() as c:
              c.execute(
                  "UPDATE menu_items SET label=%s WHERE action_type='builtin' AND action_value='cat:start_bot' AND label != %s",
                  ("🤖 رشق بدء (ستارت) بوت", "🤖 رشق بدء (ستارت) بوت")
              )
      except Exception:
          pass
      try:
          with db_conn() as c:
              svcs_with_desc = c.execute(
                  "SELECT id, description, price_per_point FROM services WHERE description IS NOT NULL AND description != ''"
              ).fetchall()
          cleaned = 0
          for s in svcs_with_desc:
              stripped = _strip_price_from_desc(s["description"], float(s["price_per_point"] or 0))
              if stripped != (s["description"] or "").strip():
                  with db_conn() as c:
                      c.execute("UPDATE services SET description=%s WHERE id=%s", (stripped, s["id"]))
                  cleaned += 1
          if cleaned:
              logger.info(f"🧹 تم تنظيف السعر من وصف {cleaned} خدمة تلقائياً.")
      except Exception as e:
          logger.warning(f"⚠️ فشل تنظيف أوصاف الأسعار: {e}")

      try:
          with db_conn() as c:
              c.execute("""
                  CREATE TABLE IF NOT EXISTS staging_services (
                      id              SERIAL PRIMARY KEY,
                      name_ar         TEXT,
                      api_service_id  INTEGER,
                      panel           INTEGER DEFAULT 1,
                      min_qty         INTEGER DEFAULT 0,
                      max_qty         INTEGER DEFAULT 0,
                      price_per_point REAL DEFAULT 0,
                      description     TEXT DEFAULT '',
                      created_at      TIMESTAMPTZ DEFAULT NOW()
                  )
              """)
      except Exception as _e:
          logger.warning(f"⚠️ staging_services table: {_e}")
