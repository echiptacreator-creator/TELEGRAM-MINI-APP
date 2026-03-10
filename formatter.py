def add_match_event_emoji(text: str) -> str:
    raw = text.strip()
    lower = raw.casefold()

    if not raw:
        return raw

    # Agar allaqachon emoji bilan boshlangan bo‘lsa, qayta qo‘shmaymiz
    known_starts = (
        "⚽", "🥅", "🎯", "🟨", "🟥", "🔁", "🚩", "📺",
        "🧤", "⛔", "🤕", "⏸", "▶️", "🏁", "📣", "🔥",
        "👏", "❌", "📯", "☕"
    )
    if raw.startswith(known_starts):
        return raw

    # Muhim: tartib muhim. Aniq eventlar tepada turadi.
    rules = [
        # Gollar
        (["avtogol", "o'z darvozasiga", "o‘z darvozasiga"], "😬⚽"),
        (["goool", "gooool", "gooooool", "gol", "goal", "gool"], "⚽"),
        (["hisobni ochdi"], "🔥"),
        (["dubl", "ikkinchi golini urdi"], "⚽⚽"),
        (["xet-trik", "hattrick", "hat-trick"], "🎩⚽"),

        # Penalti / VAR
        (["penalti gol", "penaltidan gol"], "🎯⚽"),
        (["penalti tepadi", "penalti berildi", "penalti"], "🎯"),
        (["var bekor qildi", "gol bekor qilindi", "goli bekor qilindi", "bekor qilindi"], "❌"),
        (["var", "videoyordamchi hakam"], "📺"),

        # Kartochkalar
        (["ikkinchi sariq", "2-sariq"], "🟨🟥"),
        (["ogohlantirildi", "sariq kartochka", "sariq oldi", "sariq"], "🟨"),
        (["chetlatildi", "qizil kartochka", "qizil oldi", "qizil"], "🟥"),

        # Almashtirish
        (["almashtirildi", "almashtirish", "zaxiradan tushdi", "maydonga tushdi", "o'yinni tark etdi", "o‘yinini tark etdi"], "🔁"),

        # Hujumiy holatlar
        (["xavfli vaziyat", "xavfli hujum"], "🔥"),
        (["zarba qaytardi", "seyv", "seyv qildi", "darvozabon qaytardi"], "🧤"),
        (["ustunga tegdi", "to'singa tegdi", "to‘singa tegdi"], "🥅"),
        (["darvozadan tashqariga", "aniq emas zarba", "zarba tashqarida"], "🥅"),
        (["zarba"], "🥅"),

        # Standart vaziyatlar
        (["korner", "burchak to'pi", "burchak to‘pi", "burchak"], "🚩"),
        (["offsayd", "ofsayd"], "🚩"),
        (["jarima zarbasi", "standart vaziyat"], "🎯"),

        # O‘yin holatlari
        (["jarohat", "yiqilib qoldi", "tibbiy yordam"], "🤕"),
        (["tanaffus"], "☕"),
        (["birinchi bo'lim yakunlandi", "birinchi bo‘lim yakunlandi"], "⏸"),
        (["ikkinchi bo'lim boshlandi", "ikkinchi bo‘lim boshlandi"], "▶️"),
        (["uchrashuv yakunlandi", "o'yin yakunlandi", "o‘yin yakunlandi"], "🏁"),

        # Umumiy jo‘shqin momentlar
        (["muxlislar olqishladi", "olqish"], "👏"),
        (["bosimni oshirdi", "faollikni oshirdi"], "📣"),
        (["hushtak", "final hushtak", "start hushtagi"], "📯"),
    ]

    for keywords, emoji in rules:
        if any(keyword in lower for keyword in keywords):
            return f"{emoji} {raw}"


    return raw
