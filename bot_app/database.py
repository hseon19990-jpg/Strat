"""Part of the SMMMAIN Telegram bot.

This section is loaded with the shared compatibility namespace so existing
handlers can continue to call each other while the code stays separated by
domain.
"""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

def record_first_seen(user_id: int) -> None:
    """يسجّل وقت أول /start للمستخدم (UTC) مرة واحدة فقط.

    يستخدمه بوت الإيميلات للتأكد أن المستخدم كان جديداً في هذا البوت وقت
    دخوله عبر الرابط: يقارن هذا الوقت بوقت دخوله البوت الآخر.
    """
    with db_conn() as c:
        c.execute(
            "INSERT INTO first_seen (user_id) VALUES (?) "
            "ON CONFLICT (user_id) DO NOTHING",
            (int(user_id),),
        )


def partner_ref_status(user_id: int) -> dict:
    """started: هل المستخدم موجود هنا؟ first_seen: وقت أول /start بـ UTC (أو None
    للمستخدمين القدامى الذين سبقوا هذه الميزة، فيُعدّون غير جدد)."""
    with db_conn() as c:
        row = c.execute(
            "SELECT first_seen_at FROM first_seen WHERE user_id=?", (int(user_id),)
        ).fetchone()
        if row:
            return {"started": True,
                    "first_seen": row["first_seen_at"].strftime("%Y-%m-%dT%H:%M:%S+00:00")}
        old = c.execute(
            "SELECT 1 AS x FROM users WHERE user_id=?", (int(user_id),)
        ).fetchone()
    return {"started": bool(old), "first_seen": None}


def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                # البوت المستنسخ ("إنشاء بوت كهذا") يعمل داخل مخطط PostgreSQL خاص به:
                # search_path يحوي مخططه فقط، فتُنشأ جداوله فارغة ولا يرى بيانات البوت الأصلي.
                _pool_kwargs = {"connect_timeout": 10}
                _clone_schema = os.environ.get("BOT_DB_SCHEMA", "").strip()
                if _clone_schema:
                    if not re.fullmatch(r"clone_\d+", _clone_schema):
                        raise RuntimeError("BOT_DB_SCHEMA غير صالح")
                    _pool_kwargs["options"] = f"-c search_path={_clone_schema}"
                try:
                    _pool_max = max(2, int(os.environ.get("BOT_DB_POOL_MAX", "20")))
                except ValueError:
                    _pool_max = 20
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, _pool_max, DATABASE_URL,
                    **_pool_kwargs
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
              jewels       NUMERIC(20,6) NOT NULL DEFAULT 0,
              invited_by   BIGINT DEFAULT 0,
              total_orders INTEGER DEFAULT 0,
              joined_at    TEXT DEFAULT CURRENT_DATE,
              bot_user_num INTEGER,
              verified     INTEGER DEFAULT 0
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS cloned_bots (
              id            SERIAL PRIMARY KEY,
              owner_user_id BIGINT NOT NULL,
              bot_id        BIGINT NOT NULL UNIQUE,
              bot_username  TEXT,
              bot_name      TEXT,
              token         TEXT NOT NULL,
              schema_name   TEXT NOT NULL UNIQUE,
              desired_state TEXT NOT NULL DEFAULT 'running',
              last_error    TEXT NOT NULL DEFAULT '',
              created_at    TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS first_seen (
              user_id       BIGINT PRIMARY KEY,
              first_seen_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
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
              cost_jewels  BIGINT NOT NULL DEFAULT 0,
              payment_method TEXT NOT NULL DEFAULT 'points',
              service_value_points INTEGER NOT NULL DEFAULT 0,
              telegram_payment_id TEXT,
              api_order_id TEXT DEFAULT '',
              status       TEXT DEFAULT 'pending',
               order_code   TEXT,
               created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
               provider_rate_usd REAL DEFAULT 0,
               provider_cost_usd REAL DEFAULT 0,
               partial_refund_pts INTEGER DEFAULT 0,
               refund_points INTEGER DEFAULT 0,
               refund_jewels NUMERIC(20,6) NOT NULL DEFAULT 0
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS order_inspect_snapshots (
              order_id        BIGINT PRIMARY KEY,
              order_code      TEXT,
              order_code_norm TEXT,
              user_id         BIGINT,
              data            TEXT NOT NULL,
              created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("CREATE INDEX IF NOT EXISTS order_inspect_snapshots_code_idx ON order_inspect_snapshots (order_code_norm)")
          c.execute("CREATE INDEX IF NOT EXISTS order_inspect_snapshots_time_idx ON order_inspect_snapshots (created_at)")
          c.execute("""
          CREATE TABLE IF NOT EXISTS smm_payment_intents (
              id                  BIGSERIAL PRIMARY KEY,
              user_id             BIGINT NOT NULL,
              service_id          INTEGER NOT NULL,
              service_name        TEXT NOT NULL,
              api_service_id      INTEGER NOT NULL,
              panel               INTEGER NOT NULL DEFAULT 1,
              link                TEXT NOT NULL,
              quantity            INTEGER NOT NULL,
              service_value_points INTEGER NOT NULL DEFAULT 0,
              cost_stars          INTEGER NOT NULL DEFAULT 0,
              cost_jewels         BIGINT NOT NULL DEFAULT 0,
              payment_method      TEXT,
              status              TEXT NOT NULL DEFAULT 'pending',
              telegram_payment_id TEXT UNIQUE,
              order_code          TEXT,
              last_error          TEXT,
              created_at          TIMESTAMPTZ DEFAULT NOW(),
              updated_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS jewel_transactions (
              id          BIGSERIAL PRIMARY KEY,
              user_id     BIGINT NOT NULL,
              amount      NUMERIC(20,6) NOT NULL,
              transaction_type TEXT NOT NULL,
              admin_id    BIGINT,
              reference   TEXT,
              created_at  TIMESTAMPTZ DEFAULT NOW()
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
          CREATE TABLE IF NOT EXISTS raksh_execution_usage (
              id           SERIAL PRIMARY KEY,
              user_id      BIGINT NOT NULL,
              service_type TEXT NOT NULL,
              phone_number TEXT NOT NULL,
              executed_at  TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS raksh_execution_usage_user_time_idx
          ON raksh_execution_usage (user_id, executed_at)
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS raksh_free_access (
              user_id      BIGINT NOT NULL,
              service_type TEXT NOT NULL,
              enabled      INTEGER NOT NULL DEFAULT 1,
              updated_at   TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, service_type)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_reward_tiers (
              id                  SERIAL PRIMARY KEY,
              referral_count      INTEGER NOT NULL UNIQUE,
              points_per_referral INTEGER NOT NULL DEFAULT 30,
              free_minutes        INTEGER NOT NULL DEFAULT 0,
              active              INTEGER NOT NULL DEFAULT 1,
              created_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_level_rewards (
              level       INTEGER PRIMARY KEY CHECK (level >= 2),
              points      INTEGER NOT NULL DEFAULT 0,
              jewels      NUMERIC(20,6) NOT NULL DEFAULT 0,
              created_at  TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_join_events (
              id               BIGSERIAL PRIMARY KEY,
              user_id          BIGINT NOT NULL,
              channel_username TEXT NOT NULL,
              joined_second    BIGINT NOT NULL,
              created_at       TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE (user_id, channel_username, joined_second)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS mandatory_join_events_user_idx
          ON mandatory_join_events (user_id, joined_second)
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_channel_joins (
              id               BIGSERIAL PRIMARY KEY,
              channel_username TEXT NOT NULL,
              user_id          BIGINT NOT NULL,
              joined_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS mandatory_channel_joins_chan_idx
          ON mandatory_channel_joins (channel_username)
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_fraud_log (
              id            BIGSERIAL PRIMARY KEY,
              inviter_id    BIGINT NOT NULL,
              invited_id    BIGINT NOT NULL,
              joined_count  INTEGER NOT NULL DEFAULT 0,
              total_channels INTEGER NOT NULL DEFAULT 0,
              created_at    TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_reward_claims (
              user_id     BIGINT NOT NULL,
              tier_id     INTEGER NOT NULL REFERENCES referral_reward_tiers(id) ON DELETE CASCADE,
              granted_at  TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, tier_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_daily_free_tiers (
              id                  SERIAL PRIMARY KEY,
              referral_count      INTEGER NOT NULL UNIQUE,
              free_minutes        INTEGER NOT NULL DEFAULT 0,
              active              INTEGER NOT NULL DEFAULT 1,
              created_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_daily_free_claims (
              user_id      BIGINT NOT NULL,
              tier_id      INTEGER NOT NULL REFERENCES referral_daily_free_tiers(id) ON DELETE CASCADE,
              claim_date   DATE NOT NULL DEFAULT CURRENT_DATE,
              granted_at   TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, tier_id, claim_date)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_free_access (
              user_id     BIGINT PRIMARY KEY,
              free_until  TIMESTAMPTZ NOT NULL,
              free_pass_id BIGINT NOT NULL DEFAULT 0,
              updated_at  TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute(
              "ALTER TABLE referral_free_access "
              "ADD COLUMN IF NOT EXISTS free_pass_id BIGINT NOT NULL DEFAULT 0"
          )
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_free_raksh_reservations (
              id                  BIGSERIAL PRIMARY KEY,
              user_id             BIGINT NOT NULL,
              pass_id             BIGINT NOT NULL,
              source_type         TEXT NOT NULL,
              source_id           TEXT NOT NULL,
              service_type        TEXT NOT NULL,
              reserved_quantity   INTEGER NOT NULL DEFAULT 0,
              used_quantity       INTEGER NOT NULL DEFAULT 0,
              settled_at          TIMESTAMPTZ,
              created_at          TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE (user_id, pass_id, source_type, source_id)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS referral_free_raksh_reservations_pass_idx
          ON referral_free_raksh_reservations (user_id, pass_id, settled_at)
          """)
          # The first version stored temporary free access beside the points
          # tier. Preserve that data while moving the two settings into
          # independent sections and tables.
          c.execute("""
          INSERT INTO referral_daily_free_tiers (referral_count, free_minutes, active)
          SELECT referral_count, free_minutes, active
          FROM referral_reward_tiers
          WHERE free_minutes > 0
          ON CONFLICT (referral_count) DO NOTHING
          """)
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
           CREATE TABLE IF NOT EXISTS raksh_orders (
               id            BIGSERIAL PRIMARY KEY,
               user_id       BIGINT NOT NULL,
               service_type  TEXT NOT NULL,
               quantity      INTEGER NOT NULL,
               payment_method TEXT NOT NULL,
               total_cost    INTEGER NOT NULL DEFAULT 0,
               params        JSONB NOT NULL DEFAULT '{}'::jsonb,
               status        TEXT NOT NULL DEFAULT 'pending',
               lease_until   TIMESTAMPTZ,
               last_error    TEXT,
               refund_points INTEGER NOT NULL DEFAULT 0,
               special_count INTEGER NOT NULL DEFAULT 0,
               result_text   TEXT,
               live_monitor_heartbeat_at TIMESTAMPTZ,
               created_at    TIMESTAMPTZ DEFAULT NOW(),
               updated_at    TIMESTAMPTZ DEFAULT NOW(),
               completed_at  TIMESTAMPTZ
           )""")
          c.execute("""
           CREATE INDEX IF NOT EXISTS raksh_orders_resume_idx
           ON raksh_orders (status, lease_until, updated_at)
           """)
          c.execute("""
           CREATE TABLE IF NOT EXISTS raksh_order_items (
               id            BIGSERIAL PRIMARY KEY,
               order_id      BIGINT NOT NULL REFERENCES raksh_orders(id) ON DELETE CASCADE,
               position      INTEGER NOT NULL,
               stock_id      BIGINT,
               phone_number  TEXT NOT NULL,
               is_referral_free BOOLEAN NOT NULL DEFAULT FALSE,
               status        TEXT NOT NULL DEFAULT 'pending',
               attempts      INTEGER NOT NULL DEFAULT 0,
               result_message TEXT,
               last_error    TEXT,
               updated_at    TIMESTAMPTZ DEFAULT NOW(),
               UNIQUE(order_id, phone_number)
           )""")
          c.execute(
              "ALTER TABLE raksh_order_items "
              "ADD COLUMN IF NOT EXISTS is_referral_free BOOLEAN NOT NULL DEFAULT FALSE"
          )
          c.execute("""
           CREATE TABLE IF NOT EXISTS raksh_contributor_earnings (
               id               BIGSERIAL PRIMARY KEY,
               order_id         BIGINT NOT NULL REFERENCES raksh_orders(id) ON DELETE CASCADE,
               stock_id         BIGINT NOT NULL,
               contributor_id   BIGINT NOT NULL,
               payment_method   TEXT NOT NULL,
               gross_points     INTEGER NOT NULL DEFAULT 0,
               share_percent    INTEGER NOT NULL DEFAULT 50,
               share_points     INTEGER NOT NULL DEFAULT 0,
               created_at       TIMESTAMPTZ DEFAULT NOW(),
               UNIQUE(order_id, stock_id)
           )""")
          c.execute("""
           CREATE INDEX IF NOT EXISTS raksh_contributor_earnings_user_idx
           ON raksh_contributor_earnings (contributor_id, created_at DESC)
           """)
          # ترقية قواعد البيانات القديمة التي أنشأت جداول الرشق قبل إضافة
          # الاستئناف. CREATE TABLE IF NOT EXISTS لا يضيف الأعمدة إلى جدول
          # موجود، لذلك يجب تنفيذ هذه الترقية قبل إنشاء فهارس الاستئناف.
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "params JSONB NOT NULL DEFAULT '{}'::jsonb"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "status TEXT NOT NULL DEFAULT 'pending'"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "lease_until TIMESTAMPTZ"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "last_error TEXT"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "refund_points INTEGER NOT NULL DEFAULT 0"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "special_count INTEGER NOT NULL DEFAULT 0"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "result_text TEXT"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "updated_at TIMESTAMPTZ DEFAULT NOW()"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "completed_at TIMESTAMPTZ"
          )
          c.execute(
              "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS "
              "live_monitor_heartbeat_at TIMESTAMPTZ"
          )
          c.execute(
              "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS "
              "status TEXT NOT NULL DEFAULT 'pending'"
          )
          c.execute(
              "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS "
              "attempts INTEGER NOT NULL DEFAULT 0"
          )
          c.execute(
              "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS "
              "result_message TEXT"
          )
          c.execute(
              "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS "
              "last_error TEXT"
          )
          c.execute(
              "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS "
              "updated_at TIMESTAMPTZ DEFAULT NOW()"
          )
          c.execute("""
           CREATE INDEX IF NOT EXISTS raksh_order_items_status_idx
           ON raksh_order_items (order_id, status, position)
           """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS settings (
              key   TEXT PRIMARY KEY,
              value TEXT
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS daily_gift_claims (
              user_id    BIGINT NOT NULL,
              claim_date DATE NOT NULL,
              amount     INTEGER NOT NULL,
              claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              PRIMARY KEY (user_id, claim_date)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS temporary_gifts (
              id          SERIAL PRIMARY KEY,
              points      INTEGER NOT NULL CHECK (points > 0),
              starts_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              ends_at     TIMESTAMPTZ NOT NULL,
              active      INTEGER NOT NULL DEFAULT 1,
              created_by  BIGINT NOT NULL,
              created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS temporary_gift_claims (
              gift_id    INTEGER NOT NULL REFERENCES temporary_gifts(id) ON DELETE CASCADE,
              user_id    BIGINT NOT NULL,
              amount     INTEGER NOT NULL,
              claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              PRIMARY KEY (gift_id, user_id)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS temporary_gifts_active_window_idx
          ON temporary_gifts (active, starts_at, ends_at)
          """)
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
          CREATE TABLE IF NOT EXISTS jewel_star_transactions (
              id                  BIGSERIAL PRIMARY KEY,
              user_id             BIGINT NOT NULL,
              stars               INTEGER NOT NULL CHECK (stars > 0),
              jewels_given        NUMERIC(20,6) NOT NULL CHECK (jewels_given > 0),
              telegram_payment_id TEXT NOT NULL UNIQUE,
              status              TEXT NOT NULL DEFAULT 'completed',
              created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS currency_exchange_transactions (
              id            BIGSERIAL PRIMARY KEY,
              request_id    TEXT NOT NULL UNIQUE,
              user_id       BIGINT NOT NULL,
              direction     TEXT NOT NULL CHECK (
                  direction IN ('jewels_to_points', 'points_to_jewels')
              ),
              jewels_amount NUMERIC(20,6) NOT NULL CHECK (jewels_amount > 0),
              points_amount BIGINT NOT NULL CHECK (points_amount > 0),
              rate          BIGINT NOT NULL CHECK (rate > 0),
              status        TEXT NOT NULL DEFAULT 'pending',
              created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
              added_at      TIMESTAMPTZ DEFAULT NOW(),
              contributed_by BIGINT,
              contributor_share_percent INTEGER DEFAULT 50,
               contributor_method TEXT NOT NULL DEFAULT 'number',
              sale_excluded BOOLEAN DEFAULT FALSE
          )""")
          # الحسابات المسندة إلى أدمن أرقام تُستخدم لفتح الحساب وجلب كوده،
          # لذلك لا يجوز أن تظهر في مخزون البيع في الوقت نفسه.
          c.execute("""
          CREATE TABLE IF NOT EXISTS number_admins (
              id           BIGSERIAL PRIMARY KEY,
              user_id      BIGINT NOT NULL,
              stock_id     BIGINT NOT NULL REFERENCES number_stock(id) ON DELETE CASCADE,
              phone_number TEXT NOT NULL,
              added_at     TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE(user_id, stock_id)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS number_admins_stock_idx
          ON number_admins (stock_id)
          """)

          # جداول لوحة «رشق تفاعل لكل المنشورات».
          # كانت هذه الجداول موجودة فقط في مخطط واجهة الويب، لذلك كان
          # تشغيل البوت وحده على Railway يفشل عند أول دورة للـ scheduler
          # برسالة: relation "posts" does not exist.
          c.execute("""
          CREATE TABLE IF NOT EXISTS campaigns (
              id                SERIAL PRIMARY KEY,
              name              TEXT NOT NULL,
              channel           TEXT NOT NULL,
              duration_days     INTEGER NOT NULL,
              reactions_per_post INTEGER NOT NULL,
              status            TEXT NOT NULL DEFAULT 'active',
              start_date        DATE NOT NULL,
              end_date          DATE NOT NULL,
              created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS posts (
              id                  SERIAL PRIMARY KEY,
              campaign_id         INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
              channel             TEXT NOT NULL,
              telegram_url        TEXT NOT NULL DEFAULT '',
              content             TEXT NOT NULL,
              published_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              target_reactions    INTEGER NOT NULL,
              completed_reactions INTEGER NOT NULL DEFAULT 0,
              status              TEXT NOT NULL DEFAULT 'queued',
              leave_status        TEXT NOT NULL DEFAULT 'pending'
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS accounts (
              id              SERIAL PRIMARY KEY,
              handle          TEXT NOT NULL UNIQUE,
              status          TEXT NOT NULL DEFAULT 'available',
              total_reactions INTEGER NOT NULL DEFAULT 0,
              last_action     TEXT NOT NULL DEFAULT '',
              updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS activity (
              id         SERIAL PRIMARY KEY,
              type       TEXT NOT NULL,
              message    TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              tone       TEXT NOT NULL DEFAULT 'neutral'
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS reaction_post_accounts (
              id             BIGSERIAL PRIMARY KEY,
              post_id        INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
              stock_id       BIGINT NOT NULL,
              account_handle TEXT NOT NULL DEFAULT '',
              status         TEXT NOT NULL DEFAULT 'pending',
              reaction_emoji TEXT NOT NULL DEFAULT '',
              attempts       INTEGER NOT NULL DEFAULT 0,
              reacted_at     TIMESTAMPTZ,
              leave_after    TIMESTAMPTZ,
              left_at        TIMESTAMPTZ,
              last_error     TEXT NOT NULL DEFAULT '',
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (post_id, stock_id)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS posts_status_published_idx
          ON posts (status, published_at)
          """)
          c.execute("""
          CREATE INDEX IF NOT EXISTS reaction_post_accounts_queue_idx
          ON reaction_post_accounts (status, leave_after, updated_at)
          """)

          c.execute("""
          CREATE TABLE IF NOT EXISTS mandatory_channels (
              id               SERIAL PRIMARY KEY,
              channel_username TEXT UNIQUE,
              channel_title    TEXT,
              owner_user_id    BIGINT DEFAULT 0,
              funding_type     TEXT DEFAULT 'mandatory',
              active           INTEGER DEFAULT 1
          )""")
          init_wheel_tables(c)
          for _alt in [
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS jewels NUMERIC(20,6) NOT NULL DEFAULT 0",
              "ALTER TABLE users ALTER COLUMN jewels TYPE NUMERIC(20,6) USING jewels::NUMERIC(20,6)",
              "ALTER TABLE jewel_transactions ALTER COLUMN amount TYPE NUMERIC(20,6) USING amount::NUMERIC(20,6)",
              "ALTER TABLE jewel_star_transactions ALTER COLUMN jewels_given TYPE NUMERIC(20,6) USING jewels_given::NUMERIC(20,6)",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS wheel_spins INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE prize_exchanges ALTER COLUMN points_cost TYPE NUMERIC USING points_cost::NUMERIC",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_jewels NUMERIC(20,6) NOT NULL DEFAULT 0",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cost_stars INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cost_jewels BIGINT NOT NULL DEFAULT 0",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'points'",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS service_value_points INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE orders ADD COLUMN IF NOT EXISTS telegram_payment_id TEXT",
              "CREATE UNIQUE INDEX IF NOT EXISTS orders_telegram_payment_id_unique "
              "ON orders (telegram_payment_id) WHERE telegram_payment_id IS NOT NULL AND telegram_payment_id <> ''",
              "CREATE INDEX IF NOT EXISTS smm_payment_intents_user_status_idx "
              "ON smm_payment_intents (user_id, status, created_at DESC)",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS target_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS current_members INTEGER DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS cost_stars INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE channel_funding ADD COLUMN IF NOT EXISTS cost_jewels NUMERIC(20,6) NOT NULL DEFAULT 0",
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS queued INTEGER DEFAULT 0",
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS owner_adds INTEGER NOT NULL DEFAULT 0",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS order_code TEXT",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS owner_seen BOOLEAN DEFAULT FALSE",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_at TIMESTAMPTZ",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_pts INTEGER DEFAULT 0",
              "ALTER TABLE prize_exchanges ALTER COLUMN compensated_pts TYPE NUMERIC USING compensated_pts::NUMERIC",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS compensated_reason TEXT",
              "ALTER TABLE prize_exchanges ADD COLUMN IF NOT EXISTS cost_currency TEXT DEFAULT 'points'",
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
              "ALTER TABLE account_buyback_offers ADD COLUMN IF NOT EXISTS twofa_password TEXT DEFAULT ''",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS is_solo BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS can_send_code BOOLEAN DEFAULT FALSE",
               "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'legacy'",
               "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS raksh_only BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS raksh_excluded BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS bot_session_ip TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS forced_ref_excluded BOOLEAN DEFAULT FALSE",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS contributed_by BIGINT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS contributor_share_percent INTEGER DEFAULT 50",
               "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS contributor_method TEXT NOT NULL DEFAULT 'number'",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS sale_excluded BOOLEAN DEFAULT FALSE",
              "ALTER TABLE services ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'tg'",
              "ALTER TABLE services ADD COLUMN IF NOT EXISTS source_name TEXT",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned INTEGER DEFAULT 0",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMPTZ",
              "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
              "ALTER TABLE channel_join_rewards ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT NOW()",
              "ALTER TABLE mandatory_sub_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS referral_only BOOLEAN DEFAULT FALSE",
              # كاش هوية حساب تيليجرام لبحث المالك (يوزر / ID / اسم).
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS tg_user_id BIGINT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS tg_username TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS tg_name TEXT",
              "ALTER TABLE number_stock ADD COLUMN IF NOT EXISTS tg_info_at TIMESTAMPTZ",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS reactivated_count INTEGER DEFAULT 0",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'points'",
              "ALTER TABLE forced_ref_orders ADD COLUMN IF NOT EXISTS cost_stars INTEGER DEFAULT 0",
               "ALTER TABLE raksh_execution_usage ADD COLUMN IF NOT EXISTS order_id BIGINT",
               # هذه الأعمدة أضيفت بعد إنشاء بعض قواعد البيانات القديمة؛
               # CREATE TABLE IF NOT EXISTS لا يضيفها إلى الجداول الموجودة.
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT 'points'",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS total_cost INTEGER NOT NULL DEFAULT 0",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS params JSONB NOT NULL DEFAULT '{}'::jsonb",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS last_error TEXT",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
               "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'",
               "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
               "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS result_message TEXT",
               "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS last_error TEXT",
               "ALTER TABLE raksh_order_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS refund_points INTEGER NOT NULL DEFAULT 0",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS special_count INTEGER NOT NULL DEFAULT 0",
               "ALTER TABLE raksh_orders ADD COLUMN IF NOT EXISTS result_text TEXT",
               "CREATE INDEX IF NOT EXISTS raksh_execution_usage_order_idx ON raksh_execution_usage (order_id, phone_number)",
              # جلسات مستقلة (جهاز ثانٍ منفصل) تُنشأ تلقائياً لكل رقم ليستخدمها بوت آخر.
              "CREATE TABLE IF NOT EXISTS external_bot_sessions ("
              "id BIGSERIAL PRIMARY KEY, phone_number TEXT NOT NULL UNIQUE, "
              "source_stock_id BIGINT, session_string TEXT, "
              "status TEXT NOT NULL DEFAULT 'pending', fail_reason TEXT, "
              "attempts INTEGER NOT NULL DEFAULT 0, "
              "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ready_at TIMESTAMPTZ, "
              "delivered INTEGER NOT NULL DEFAULT 0, delivered_at TIMESTAMPTZ)",
              "CREATE INDEX IF NOT EXISTS external_bot_sessions_status_idx ON external_bot_sessions (status)",
          ]:
              try: c.execute(_alt)
              except Exception: pass
          # ── انضمامات عبر رابط البوت: أعمدة جديدة ──
          for _alt2 in (
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS bot_invite_link TEXT",
              "ALTER TABLE mandatory_channels ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ",
          ):
              try: c.execute(_alt2)
              except Exception: pass
          try:
              _has_via = c.execute(
                  "SELECT 1 FROM information_schema.columns "
                  "WHERE table_schema = current_schema() AND table_name='mandatory_channel_joins' AND column_name='via_bot'"
              ).fetchone()
              if not _has_via:
                  c.execute("ALTER TABLE mandatory_channel_joins ADD COLUMN via_bot BOOLEAN NOT NULL DEFAULT FALSE")
                  # الانضمامات المسجّلة قبل تتبّع الرابط: تُعدّ عبر البوت إن كان المنضم مستخدماً للبوت (تقدير لمرة واحدة)
                  c.execute(
                      "UPDATE mandatory_channel_joins j SET via_bot=TRUE "
                      "WHERE EXISTS (SELECT 1 FROM users u WHERE u.user_id=j.user_id)"
                  )
          except Exception as _via_err:
              logger.warning(f"mandatory joins via_bot migration: {_via_err}")
          # ── عدّاد انضمامات القنوات الإجبارية: رصيد ما قبل التحديث (يُحسب مرة واحدة) ──
          try:
              _has_base = c.execute(
                  "SELECT 1 FROM information_schema.columns "
                  "WHERE table_schema = current_schema() AND table_name='mandatory_channels' AND column_name='joins_baseline'"
              ).fetchone()
              if not _has_base:
                  c.execute("ALTER TABLE mandatory_channels ADD COLUMN joins_baseline BIGINT NOT NULL DEFAULT 0")
                  # تقدير من السجلات القديمة: أكبر قيمة بين أحداث الانضمام المسجّلة قبل أول
                  # انضمام جديد، وعدّاد التمويل بعد طرح الانضمامات الجديدة (حتى لا تتكرر).
                  c.execute(
                      """
                      UPDATE mandatory_channels mc SET joins_baseline = GREATEST(
                          COALESCE((
                              SELECT COUNT(*) FROM mandatory_join_events e
                              WHERE LOWER(e.channel_username) = LOWER(mc.channel_username)
                                AND e.created_at < COALESCE((
                                    SELECT MIN(j.joined_at) FROM mandatory_channel_joins j
                                    WHERE LOWER(j.channel_username) = LOWER(mc.channel_username)
                                ), 'infinity'::timestamptz)
                          ), 0),
                          GREATEST(0,
                              COALESCE((
                                  SELECT SUM(f.current_members) FROM channel_funding f
                                  WHERE LOWER(f.channel_username) = LOWER(mc.channel_username)
                                    AND COALESCE(f.status,'') <> 'refunded'
                              ), 0)
                              - COALESCE((
                                  SELECT COUNT(*) FROM mandatory_channel_joins j2
                                  WHERE LOWER(j2.channel_username) = LOWER(mc.channel_username)
                              ), 0)
                          )
                      )
                      """
                  )
          except Exception as _base_err:
              logger.warning(f"mandatory joins baseline migration: {_base_err}")
          # ── مصدر الجواهر: الجواهر المحصّلة عبر الإحالة وحدها تصلح لاستبدال الجوائز المخصصة ──
          try:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_jewels NUMERIC(20,6) NOT NULL DEFAULT 0")
              c.execute(
                  """
                  CREATE OR REPLACE FUNCTION clamp_referral_jewels() RETURNS trigger AS $$
                  BEGIN
                      IF NEW.referral_jewels > COALESCE(NEW.jewels, 0) THEN
                          NEW.referral_jewels := GREATEST(COALESCE(NEW.jewels, 0), 0);
                      END IF;
                      RETURN NEW;
                  END;
                  $$ LANGUAGE plpgsql
                  """
              )
              c.execute("DROP TRIGGER IF EXISTS users_clamp_referral_jewels ON users")
              c.execute(
                  "CREATE TRIGGER users_clamp_referral_jewels BEFORE UPDATE ON users "
                  "FOR EACH ROW EXECUTE FUNCTION clamp_referral_jewels()"
              )
              _done = c.execute(
                  "SELECT value FROM settings WHERE key='referral_jewels_backfilled'"
              ).fetchone()
              if not _done:
                  c.execute(
                      """
                      UPDATE users u SET referral_jewels = LEAST(
                          COALESCE(u.jewels, 0),
                          COALESCE((SELECT SUM(t.amount) FROM jewel_transactions t
                                    WHERE t.user_id = u.user_id
                                      AND t.transaction_type = 'referral'), 0)
                      )
                      """
                  )
                  c.execute(
                      "INSERT INTO settings (key, value) VALUES ('referral_jewels_backfilled','1') "
                      "ON CONFLICT (key) DO NOTHING"
                  )
          except Exception as _rj_err:
              logger.warning(f"referral_jewels migration: {_rj_err}")
          # السجلات القديمة لا تملك مصدر استيراد محفوظاً. نضع لها تصنيفاً
          # آمناً قابلاً للتعديل: الرقم بلا جلسة = يدوي، والجلسة القديمة = ملف.
          try:
              c.execute(
                  """
                  UPDATE number_stock
                  SET source_type = CASE
                      WHEN raksh_only IS TRUE THEN 'raksh'
                      WHEN session_string IS NULL OR BTRIM(session_string) = '' THEN 'manual'
                      ELSE 'file'
                  END
                  WHERE source_type IS NULL
                     OR BTRIM(source_type) = ''
                     OR source_type = 'legacy'
                  """
              )
          except Exception:
              pass
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
          try:
              # سعر الباقة بالجواهر يحدده المالك لكل باقة (NULL = باقة قديمة تُسعَّر بالمعدل).
              c.execute("ALTER TABLE exchange_star_packages ADD COLUMN IF NOT EXISTS jewels NUMERIC(18,6)")
          except Exception:
              pass
          c.execute("""
          CREATE TABLE IF NOT EXISTS channel_join_rewards (
              user_id    BIGINT,
              channel_id BIGINT,
              joined_at  TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (user_id, channel_id)
          )""")
          c.execute("""
          CREATE TABLE IF NOT EXISTS raksh_channel_memberships (
              id                  SERIAL PRIMARY KEY,
              phone_number        TEXT NOT NULL,
              channel_ref         TEXT NOT NULL,
              telegram_channel_id BIGINT,
              joined_at           TIMESTAMPTZ DEFAULT NOW(),
              leave_at            TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '72 hours'),
              UNIQUE (phone_number, channel_ref)
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS raksh_channel_memberships_due_idx
          ON raksh_channel_memberships (leave_at)
          """)
          c.execute("""
          CREATE INDEX IF NOT EXISTS raksh_channel_memberships_channel_idx
          ON raksh_channel_memberships (channel_ref)
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS referral_tasks (
              id                  SERIAL PRIMARY KEY,
              label               TEXT NOT NULL,
              bot_username        TEXT NOT NULL,
              start_param         TEXT NOT NULL,
              mandatory_channels  TEXT DEFAULT '',
              folder_link         TEXT DEFAULT '',
              use_ai              BOOLEAN DEFAULT TRUE,
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
          CREATE TABLE IF NOT EXISTS account_buyback_offers (
              id               SERIAL PRIMARY KEY,
              seller_user_id   BIGINT NOT NULL,
              phone_number     TEXT NOT NULL,
              account_username TEXT DEFAULT '',
              session_string   TEXT,
              twofa_password   TEXT DEFAULT '',
              quoted_price     INTEGER DEFAULT 0,
              status           TEXT DEFAULT 'awaiting_seller_confirm',
              accepted_at     TIMESTAMPTZ,
              next_check_at   TIMESTAMPTZ,
              last_checked_at TIMESTAMPTZ,
              paid_at         TIMESTAMPTZ,
              rejection_reason TEXT DEFAULT '',
              created_at      TIMESTAMPTZ DEFAULT NOW(),
              updated_at      TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE INDEX IF NOT EXISTS account_buyback_status_idx
          ON account_buyback_offers (status, next_check_at)
          """)
          c.execute("""
          CREATE TABLE IF NOT EXISTS tg_number_orders (
              id                  SERIAL PRIMARY KEY,
              order_code          TEXT,
              user_id             BIGINT NOT NULL,
              user_name           TEXT DEFAULT '',
              user_username       TEXT DEFAULT '',
              country_code        TEXT NOT NULL,
              country_name        TEXT DEFAULT '',
              base_price_cents    INTEGER NOT NULL DEFAULT 0,
              price_cents         INTEGER NOT NULL DEFAULT 0,
              payment_method      TEXT NOT NULL,
              amount              BIGINT NOT NULL DEFAULT 0,
              status              TEXT NOT NULL DEFAULT 'awaiting_payment',
              telegram_payment_id TEXT,
              notified_at         TIMESTAMPTZ,
              paid_at             TIMESTAMPTZ,
              completed_at        TIMESTAMPTZ,
              completed_by        BIGINT,
              created_at          TIMESTAMPTZ DEFAULT NOW(),
              updated_at          TIMESTAMPTZ DEFAULT NOW()
          )""")
          c.execute("""
          CREATE UNIQUE INDEX IF NOT EXISTS tg_number_orders_charge_idx
          ON tg_number_orders (telegram_payment_id)
          WHERE telegram_payment_id IS NOT NULL
          """)
          c.execute("""
          CREATE INDEX IF NOT EXISTS tg_number_orders_status_idx
          ON tg_number_orders (status, id)
          """)
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
          
          # ==================== جداول البايو واليوزر ====================
          c.execute("""
          CREATE TABLE IF NOT EXISTS account_bio_assignments (
              phone_number  TEXT PRIMARY KEY,
              assigned_bio  TEXT NOT NULL,
              assigned_at   TIMESTAMPTZ DEFAULT NOW()
          )
          """)

          c.execute("""
          CREATE TABLE IF NOT EXISTS account_username_assignments (
              phone_number     TEXT PRIMARY KEY,
              assigned_username TEXT NOT NULL,
              assigned_at      TIMESTAMPTZ DEFAULT NOW()
          )
          """)
          
          default_settings = [
              ('join_channel_reward', '45'),
              ('daily_gift_points', '100'),
              ('referral_points', '30'),
              ('referral_reward_type', 'points'),
              ('referral_fraud_protection', '0'),
              ('referral_jewels', '0'),
              ('star_to_points', '250'),
              ('jewels_per_star', '1'),
              ('wheel_spin_price_stars', '1'),
              ('wheel_spin_price_jewels', '1'),
              ('wheel_ten_price_stars', '9'),
              ('wheel_ten_price_jewels', '9'),
              ('raksh_points_per_jewel', '1000'),
              ('jewels_to_points_rate', '5000'),
              ('points_to_jewels_rate', '7000'),
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
              ('jewels_asiacell_text', '💎 لشحن المجوهرات عبر آسيا سيل، اتبع تعليمات التحويل ثم اضغط «التواصل مع المالك» لإرسال طلبك.'),
              ('jewels_ewallet_text', '💎 لشحن المجوهرات عبر العملات الإلكترونية، اتبع تعليمات التحويل ثم اضغط «التواصل مع المالك» لإرسال طلبك.'),
              ('captcha_enabled', '0'),
              ('phone_verification_enabled', '1'),
              ('maintenance_mode', '0'),
              ('number_exchange_enabled', '0'),
              ('buyback_visible', '0'),
              ('buyback_price', '7000'),
              ('buyback_restricted_price', '4000'),
              ('legendary_services_visible', '1'),
              ('legendary_owner_phones', '8801709839107'),
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
              ('openai_api_key',                ''),
              ('referral_task_delay',            '30'),  # تأخير بين الحسابات في مهام الإحالة (ثوانٍ)
              ('internal_leave_grace_hours', '24'),
              ('raksh_channel_leave_hours', '72'),
              ('gmail_points_reward', '10000'),
              ('gmail_intro_message', 'للحصول على النقاط يجب عليك تقديم حساب جيميل لا تستخدمه، سيتم مراجعته من قبل المالك وإضافة النقاط بعد التحقق.'),
              ('gmail_button_label', '📧 احصل على نقاط مقابل إيميل جيميل'),
              ('gmail_redirect_url', ''),
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
          # استبدال الاسم الافتراضي القديم بالاسم الجديد فقط؛
          # لا نلمس أي اسم مخصص اختاره المالك بنفسه.
          c.execute(
              "UPDATE settings SET value=%s "
              "WHERE key=%s AND value IN (%s, %s, %s)",
              (
                  "خدمات تلي مميزة",
                  "raksh_accounts_label",
                  "حسابات خدمات الرشق",
                  "خدمات الرشق",
                  "خدمات المرتقى",
              ),
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
              c.execute(
                  "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                  "referral_credited INTEGER DEFAULT 0"
              )
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute(
                  "ALTER TABLE orders ADD COLUMN IF NOT EXISTS "
                  "provider_rate_usd REAL DEFAULT 0"
              )
              c.execute(
                  "ALTER TABLE orders ADD COLUMN IF NOT EXISTS "
                  "provider_cost_usd REAL DEFAULT 0"
              )
              c.execute(
                  "ALTER TABLE orders ADD COLUMN IF NOT EXISTS "
                  "partial_refund_pts INTEGER DEFAULT 0"
              )
              c.execute(
                  "ALTER TABLE orders ADD COLUMN IF NOT EXISTS "
                  "refund_points INTEGER DEFAULT 0"
              )
              # الطلبات الجزئية التي عُوّضت قبل إضافة refund_points يجب أن
              # تبقى محمية من أي تعويض ثانٍ.
              c.execute(
                  "UPDATE orders SET refund_points=partial_refund_pts "
                  "WHERE COALESCE(refund_points, 0)=0 "
                  "AND COALESCE(partial_refund_pts, 0)>0"
              )
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_points_blocked INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              # إحالة مرفوضة نهائياً لأن المدعو دخل بلا يوزر؛ لا تُحتسب حتى لو أضاف يوزراً لاحقاً.
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_rejected INTEGER DEFAULT 0")
      except Exception:
          pass
      try:
          with db_conn() as c:
              c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credited_at TIMESTAMPTZ")
              # المستخدم غير المتحقق لم يحصل على مكافأة بعد؛ لا نسمح
              # لمايغريشن قديم أن يتركه بحالة credited بلا نقاط.
              c.execute(
                  "UPDATE users SET referral_credited=0, credited_at=NULL "
                  "WHERE invited_by IS NOT NULL AND invited_by != 0 "
                  "AND verified=0 AND referral_credited IS DISTINCT FROM 0"
              )
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
              c.execute("ALTER TABLE referral_tasks ADD COLUMN IF NOT EXISTS use_ai BOOLEAN DEFAULT TRUE")
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
