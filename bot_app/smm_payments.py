"""Payment helpers for services supplied by external SMM panels."""

from . import shared as _shared
globals().update({key: value for key, value in vars(_shared).items() if not key.startswith("__")})

from .services import smm_jewels_cost, smm_stars_cost


def create_smm_payment_intent(user_id: int, service: dict, link: str, quantity: int, service_value_points: int) -> dict:
    """Save the quoted SMM order and both payment amounts before showing checkout."""
    service_value_points = max(0, int(service_value_points or 0))
    with db_conn() as c:
        row = c.execute(
            """
            INSERT INTO smm_payment_intents
                (user_id, service_id, service_name, api_service_id, panel, link,
                 quantity, service_value_points, cost_stars, cost_jewels)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            (
                user_id,
                int(service["id"]),
                str(service.get("name_ar") or "الخدمة"),
                int(service["api_service_id"]),
                int(service.get("panel") or 1),
                link,
                int(quantity),
                service_value_points,
                smm_stars_cost(service_value_points),
                smm_jewels_cost(service_value_points),
            ),
        ).fetchone()
    return dict(row)


def get_smm_payment_intent(intent_id: int, user_id: int | None = None) -> dict | None:
    with db_conn() as c:
        if user_id is None:
            row = c.execute(
                "SELECT * FROM smm_payment_intents WHERE id=%s",
                (intent_id,),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM smm_payment_intents WHERE id=%s AND user_id=%s",
                (intent_id, user_id),
            ).fetchone()
    return dict(row) if row else None


def start_smm_stars_invoice(intent_id: int, user_id: int) -> dict | None:
    """Reserve one invoice for an intent; older or already-used buttons cannot bill."""
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE smm_payment_intents
            SET status='awaiting_payment', payment_method='stars', updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='pending'
              AND created_at > NOW() - INTERVAL '1 day'
            RETURNING *
            """,
            (intent_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def reset_smm_stars_invoice(intent_id: int, user_id: int) -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE smm_payment_intents
            SET status='pending', payment_method=NULL, updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='awaiting_payment'
              AND telegram_payment_id IS NULL
            """,
            (intent_id, user_id),
        )


def validate_smm_stars_invoice(intent_id: int, user_id: int, stars: int) -> bool:
    with db_conn() as c:
        row = c.execute(
            """
            SELECT id FROM smm_payment_intents
            WHERE id=%s AND user_id=%s AND payment_method='stars'
              AND status='awaiting_payment' AND cost_stars=%s
              AND created_at > NOW() - INTERVAL '1 day'
            """,
            (intent_id, user_id, stars),
        ).fetchone()
    return bool(row)


def claim_smm_stars_payment(
    intent_id: int,
    user_id: int,
    stars: int,
    charge_id: str,
) -> tuple[str, dict | None]:
    """Claim a paid invoice exactly once; report a second charge for refund."""
    with db_conn() as c:
        row = c.execute(
            "SELECT * FROM smm_payment_intents WHERE id=%s FOR UPDATE",
            (intent_id,),
        ).fetchone()
        if not row or int(row["user_id"]) != int(user_id) or int(row["cost_stars"]) != int(stars):
            return "invalid", None
        if row["status"] == "awaiting_payment" and row["payment_method"] == "stars":
            c.execute(
                """
                UPDATE smm_payment_intents
                SET status='processing', telegram_payment_id=%s, updated_at=NOW()
                WHERE id=%s
                """,
                (charge_id, intent_id),
            )
            return "claimed", dict(row)
        if row.get("telegram_payment_id") == charge_id:
            return "duplicate_update", dict(row)
        return "duplicate_charge", dict(row)


def claim_smm_jewel_payment(intent_id: int, user_id: int) -> tuple[str, dict | None, int | None]:
    """Atomically reserve the intent, deduct jewels, and append its ledger entry."""
    with db_conn() as c:
        row = c.execute(
            """
            SELECT * FROM smm_payment_intents
            WHERE id=%s AND user_id=%s
            FOR UPDATE
            """,
            (intent_id, user_id),
        ).fetchone()
        if (
            not row
            or row["status"] != "pending"
            or int(row["cost_jewels"] or 0) <= 0
            or row["created_at"] is None
        ):
            return "unavailable", None, None
        fresh = c.execute(
            "SELECT id FROM smm_payment_intents WHERE id=%s "
            "AND created_at > NOW() - INTERVAL '1 day'",
            (intent_id,),
        ).fetchone()
        if not fresh:
            return "expired", None, None
        updated = c.execute(
            """
            UPDATE users SET jewels=COALESCE(jewels,0)-%s
            WHERE user_id=%s AND COALESCE(jewels,0)>=%s
            RETURNING jewels
            """,
            (int(row["cost_jewels"]), user_id, int(row["cost_jewels"])),
        ).fetchone()
        if not updated:
            return "insufficient", dict(row), None
        c.execute(
            "INSERT INTO jewel_transactions "
            "(user_id,amount,transaction_type,reference) "
            "VALUES (%s,%s,'spend',%s)",
            (user_id, -int(row["cost_jewels"]), f"smm_intent:{intent_id}"),
        )
        claimed = c.execute(
            """
            UPDATE smm_payment_intents
            SET status='processing', payment_method='jewels', updated_at=NOW()
            WHERE id=%s AND status='pending'
            RETURNING id
            """,
            (intent_id,),
        ).fetchone()
        if not claimed:
            raise RuntimeError(f"SMM payment intent {intent_id} changed while locked")
        result = dict(row)
        result["payment_method"] = "jewels"
    return "claimed", result, updated["jewels"]


def claim_smm_free_order(intent_id: int, user_id: int) -> tuple[str, dict | None]:
    """Preserve explicitly free/referral-waived orders without touching points."""
    with db_conn() as c:
        row = c.execute(
            """
            UPDATE smm_payment_intents
            SET status='processing', payment_method='free', updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='pending'
              AND service_value_points=0
              AND created_at > NOW() - INTERVAL '1 day'
            RETURNING *
            """,
            (intent_id, user_id),
        ).fetchone()
    return ("claimed", dict(row)) if row else ("unavailable", None)


async def execute_smm_payment_intent(
    context,
    intent: dict,
    payment_method: str,
    paid_amount: int,
    telegram_payment_id: str = "",
) -> dict:
    """Submit one confirmed order to its provider and persist the chosen currency."""
    user_id = int(intent["user_id"])
    service_id = int(intent["service_id"])
    quantity = int(intent["quantity"])
    panel = int(intent.get("panel") or 1)
    api_service_id = int(intent["api_service_id"])
    service_name = str(intent.get("service_name") or "الخدمة")
    link = str(intent["link"])

    try:
        balance_response = await asyncio.to_thread(
            smm_request, "balance", panel=panel
        )
    except Exception:
        logger.exception("تعذر فحص رصيد موقع الرشق قبل الطلب")
        balance_response = {}
    provider_balance = provider_rate = required_balance = None
    try:
        provider_balance = float(
            str(balance_response.get("balance", "")).replace(",", "").strip()
        )
        provider_info = await asyncio.to_thread(
            smm_service_info, api_service_id, panel=panel
        )
        provider_rate = float(provider_info.get("rate", 0) or 0)
        required_balance = (provider_rate * quantity) / 1000
    except (AttributeError, TypeError, ValueError, KeyError):
        pass
    except Exception:
        logger.exception("تعذر قراءة سعر الخدمة من موقع الرشق")

    if (
        provider_balance is not None
        and provider_rate is not None
        and provider_rate > 0
        and required_balance is not None
        and provider_balance < required_balance
    ):
        currency = str(balance_response.get("currency") or "USD")
        warning = (
            "⚠️ رصيد موقع الرشق غير كافٍ لتنفيذ طلب جديد\n"
            f"الخدمة: {service_name}\n"
            f"الرصيد الحالي: {provider_balance:.4f} {currency}\n"
            f"المطلوب تقريباً: {required_balance:.4f} {currency}\n"
            f"المستخدم: {user_id}"
        )
        try:
            if OWNER_ID:
                await context.bot.send_message(OWNER_ID, warning)
        except Exception as notify_error:
            logger.warning(f"تعذر إرسال تنبيه نقص رصيد المزود للمالك: {notify_error}")
        return {"ok": False, "provider_balance_error": True}

    api_res = await asyncio.to_thread(
        smm_create_order,
        api_service_id,
        link,
        quantity,
        panel=panel,
    )
    if "error" in api_res or not api_res.get("order"):
        error_text = str(api_res.get("error") or "خطأ غير معروف من الموقع")
        error_lower = error_text.casefold()
        provider_balance_error = any(
            marker in error_lower
            for marker in (
                "insufficient balance",
                "insufficient funds",
                "not enough balance",
                "low balance",
                "رصيد غير كاف",
                "الرصيد غير كاف",
                "رصيد الموقع",
            )
        )
        if provider_balance_error:
            try:
                if OWNER_ID:
                    await context.bot.send_message(
                        OWNER_ID,
                        "⚠️ تعذر تنفيذ طلب بسبب عدم كفاية رصيد موقع الرشق\n"
                        f"الخدمة: {service_name}\n"
                        f"الكمية: {quantity}\n"
                        f"المستخدم: {user_id}\n"
                        f"تفاصيل الموقع: {error_text}",
                    )
            except Exception as notify_error:
                logger.warning(f"تعذر إرسال تنبيه نقص رصيد المزود للمالك: {notify_error}")
        return {
            "ok": False,
            "provider_balance_error": provider_balance_error,
            "error": error_text,
        }

    if provider_rate is None or provider_rate <= 0:
        try:
            provider_info = await asyncio.to_thread(
                smm_service_info, api_service_id, panel=panel
            )
            provider_rate = float(provider_info.get("rate", 0) or 0)
        except (AttributeError, TypeError, ValueError, KeyError):
            provider_rate = 0
        except Exception:
            logger.exception("تعذر قراءة تكلفة مزود الرشق بعد إرسال الطلب")
            provider_rate = 0
    provider_cost_usd = (
        (provider_rate * quantity) / 1000
        if provider_rate > 0 and quantity > 0
        else 0
    )
    api_order_id = str(api_res.get("order", ""))
    order_code = next_order_code(user_id)
    cost_stars = int(paid_amount) if payment_method == "stars" else 0
    cost_jewels = int(paid_amount) if payment_method == "jewels" else 0
    currency_label = {
        "stars": "نجمة",
        "jewels": "مجوهرة",
        "free": "مجاناً",
    }.get(payment_method, "نقطة")
    paid_text = (
        "مجاناً"
        if payment_method == "free"
        else f"{int(paid_amount):,} {currency_label}"
    )

    with db_conn() as c:
        c.execute(
            """
            INSERT INTO orders
                (user_id,service_id,link,quantity,cost_points,cost_stars,
                 cost_jewels,payment_method,service_value_points,
                 telegram_payment_id,api_order_id,order_code,
                 provider_rate_usd,provider_cost_usd)
            VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                user_id,
                service_id,
                link,
                quantity,
                cost_stars,
                cost_jewels,
                payment_method,
                int(intent.get("service_value_points") or 0),
                telegram_payment_id or None,
                api_order_id,
                order_code,
                provider_rate,
                provider_cost_usd,
            ),
        )
        c.execute(
            """
            UPDATE smm_payment_intents
            SET status='completed', order_code=%s, updated_at=NOW()
            WHERE id=%s AND status='processing'
            """,
            (order_code, int(intent["id"])),
        )

    try:
        await context.bot.send_message(
            user_id,
            "✅ تم إرسال طلبك إلى موقع الرشق.\n\n"
            f"🔹 الخدمة: {html.escape(service_name, quote=False)}\n"
            f"🔢 الكمية: {quantity}\n"
            f"💳 المدفوع: {paid_text}\n"
            f"📌 كود الطلب: <code>{order_code}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("تعذر إرسال إيصال طلب SMM إلى المستخدم %s", user_id)
    try:
        await notify_group(
            context.application,
            format_service_order_group_message(
                service_name,
                quantity,
                int(paid_amount),
                order_code,
                currency_label=currency_label,
            ),
        )
    except Exception:
        logger.exception("تعذر إرسال إشعار طلب SMM إلى مجموعة الإدارة")
    return {"ok": True, "order_code": order_code, "api_order_id": api_order_id}


def finish_smm_payment_intent(intent_id: int, status: str, error: str = "") -> None:
    with db_conn() as c:
        c.execute(
            """
            UPDATE smm_payment_intents
            SET status=%s, last_error=%s, updated_at=NOW()
            WHERE id=%s AND status='processing'
            """,
            (status, (error or "")[:1000] or None, intent_id),
        )
