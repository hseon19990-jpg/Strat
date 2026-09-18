"""QR decoding helpers used by the Telegram login flow."""


def decode_login_qr_value(image) -> str | None:
    """Return the text embedded in the first readable QR/barcode.

    Telegram screenshots often contain a QR with a logo in the middle.  OpenCV
    can locate that code but may fail to decode it, so ZXing is tried first.
    OpenCV remains as a fallback so the login flow still works if ZXing is
    temporarily unavailable.
    """
    try:
        import zxingcpp

        for barcode in zxingcpp.read_barcodes(image):
            value = str(getattr(barcode, "text", "") or "").strip()
            if value:
                return value
    except Exception:
        # Keep the existing OpenCV path available for older deployments or
        # images ZXing cannot process.
        pass

    try:
        import cv2
    except Exception:
        return None

    detector = cv2.QRCodeDetector()
    candidates = [image]
    try:
        if getattr(image, "ndim", 0) == 3:
            candidates.append(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    except Exception:
        pass

    for candidate in candidates:
        try:
            value, _, _ = detector.detectAndDecode(candidate)
            value = str(value or "").strip()
            if value:
                return value
        except Exception:
            continue

        try:
            detected, values, _, _ = detector.detectAndDecodeMulti(candidate)
            if detected:
                for value in values or ():
                    value = str(value or "").strip()
                    if value:
                        return value
        except Exception:
            continue

    return None