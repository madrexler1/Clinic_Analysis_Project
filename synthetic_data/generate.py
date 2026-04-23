"""Generate synthetic Smartemis line-item CSVs that mirror the real schema.

Use this for all local development. Real FR/DE customer data must never leave
the EU; synthetic data has no such restriction and lets us iterate on the
pipeline without any GDPR exposure.

Schema mirrors the observed export:
    Rechnungsnummer, BehandlungDatum, Rechnungsdatum, Artikel Typ,
    Artikel Gruppe, Artikel Nummer GOT, Tierart, Mitarbeiter, Kurzbericht,
    Brand Name, KundePLZ, Umsatz netto, Standort, TierGeburtsdatum,
    TierRasse, Anz. Tiere, Anzahl Behandl., Betrag netto, Anzahl/Menge,
    Faktor, BehandlungNummer, Berechnet, Bezahlt

Run:
    python -m synthetic_data.generate --invoices 2000 --clinics 12 --out out/
"""
from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SPECIES = ["Hund", "Katze", "Kaninchen", "Vogel"]
BREEDS_DOG = ["Dansky", "Yorkshire", "Border Collie", "Labrador", "Mischling", "Dackel"]
BREEDS_CAT = ["EKH", "BKH", "Maine Coon", "Perser", "Siam"]
BREEDS_RABBIT = ["Zwergwidder", "Löwenkopf"]
BREEDS_BIRD = ["Wellensittich", "Nymphensittich"]

ARTIKEL_TYP = ["Leistungen", "Angewandt", "Abgegeben", "Artikel"]

ARTIKEL_GRUPPE = {
    "Leistungen": [
        ("Grundleistung 34", "34"),
        ("Grundleistung 221", "221"),
        ("Grundleistung § 4 Abs. 1", "4-1"),
        ("Radiologie 167", "167"),
        ("Radiologie 180", "180"),
        ("Gastroenterologie 434", "434"),
        ("Grundleistung 83", "83"),
        ("Dokumentation 88", "88"),
        ("Grundleistung 16", "16"),
    ],
    "Angewandt": [
        ("Antibiotika", "A01"),
        ("Analgetika", "A02"),
        ("Antiemetika", "A03"),
    ],
    "Abgegeben": [
        ("Analgetika", "D01"),
        ("Laxativum", "D02"),
        ("Verdauung", "D03"),
        ("Antibiotika", "D04"),
    ],
    "Artikel": [
        ("Pauschale", "P01"),
        ("Laxativum", "P02"),
    ],
}

BRAND_BY_GRUPPE = {
    "Antibiotika": ["Duphamox", "Synulox", "Nicilan"],
    "Analgetika": ["Novaminsulfon", "Metacam", "Onsior"],
    "Antiemetika": ["Prevomax", "Cerenia"],
    "Laxativum": ["Microlax", "Paraffinum"],
    "Verdauung": ["Vetgastril", "Gastroenteritis", "Tkb"],
    "Grundleistung 34": ["Folgeuntersuchung"],
    "Grundleistung 221": ["Injektion"],
    "Grundleistung § 4 Abs. 1": ["Notdienstgebühr"],
    "Radiologie 167": ["Röntgen"],
    "Radiologie 180": ["Ultraschall"],
    "Gastroenterologie 434": ["Gastroenterologie"],
    "Grundleistung 83": ["Stationäre"],
    "Dokumentation 88": ["Euthanasie"],
    "Grundleistung 16": ["Allgemeine"],
    "Pauschale": ["Mp"],
}

KURZBERICHT = [
    "Wundkontrolle",
    "Röntgenkontrolle",
    "Stationär",
    "Vorstellung",
    "Notdienst",
    "Autounfall",
    "Impfung",
    "Kastration",
    "Zahnbehandlung",
]

# Synthetic German vet names — safe for a generator, but we still treat
# Mitarbeiter as PII in the pipeline so the PII path is exercised end-to-end.
SYNTHETIC_VETS = [
    "Dr. Elisabeth Schulz",
    "Dr. Thomas Weber",
    "Bianca Steiner",
    "Dr. Markus Koch",
    "Dr. Anna Bauer",
    "Claudia Hoffmann",
    "Dr. Jens Wagner",
    "Dr. Sabine Fischer",
]

# Bavarian + Berlin + Hamburg PLZ prefixes (2-digit buckets we'll preserve)
PLZ_POOL = ["83", "80", "81", "82", "84", "14", "10", "20", "22", "50", "60"]

CLINIC_SITES = [f"DE{1000 + i:04d}" for i in range(1, 50)]


@dataclass
class Clinic:
    standort: str
    vets: list[str]
    plz_prefixes: list[str]
    faktor_strategy: float  # avg GOT factor — encodes pricing posture

    @classmethod
    def random(cls, idx: int, rng: random.Random) -> "Clinic":
        return cls(
            standort=CLINIC_SITES[idx],
            vets=rng.sample(SYNTHETIC_VETS, k=rng.randint(3, 6)),
            plz_prefixes=rng.sample(PLZ_POOL, k=rng.randint(2, 4)),
            faktor_strategy=rng.uniform(1.0, 2.8),
        )


def random_pet_birthdate(rng: random.Random, today: date) -> date:
    age_days = rng.randint(30, 365 * 18)
    return today - timedelta(days=age_days)


def pick_breed(rng: random.Random, species: str) -> str:
    if species == "Hund":
        return rng.choice(BREEDS_DOG)
    if species == "Katze":
        return rng.choice(BREEDS_CAT)
    if species == "Kaninchen":
        return rng.choice(BREEDS_RABBIT)
    return rng.choice(BREEDS_BIRD)


def de_date(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def generate(invoices: int, clinics: int, out_path: Path, seed: int) -> Path:
    rng = random.Random(seed)
    clinic_pool = [Clinic.random(i, rng) for i in range(clinics)]

    start = date(2025, 1, 1)
    end = date(2025, 12, 31)
    span = (end - start).days

    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "Rechnungsnummer",
        "BehandlungDatum",
        "Rechnungsdatum",
        "Artikel Typ",
        "Artikel Gruppe",
        "Artikel Nummer GOT",
        "Tierart",
        "Mitarbeiter",
        "Kurzbericht",
        "Brand Name",
        "KundePLZ",
        "Umsatz netto",
        "Standort",
        "TierGeburtsdatum",
        "TierRasse",
        "Anz. Tiere",
        "Anzahl Behandl.",
        "Betrag netto",
        "Anzahl/Menge",
        "Faktor",
        "BehandlungNummer",
        "Berechnet",
        "Bezahlt",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(headers)

        invoice_num = 0
        treatment_num = 318600
        for _ in range(invoices):
            clinic = rng.choice(clinic_pool)
            invoice_num += 1
            rechnungsnummer = f"25-{invoice_num:06d}"
            behandlung_datum = start + timedelta(days=rng.randint(0, span))
            rechnungsdatum = behandlung_datum + timedelta(days=rng.randint(0, 7))

            tierart = rng.choice(SPECIES)
            rasse = pick_breed(rng, tierart)
            geburt = random_pet_birthdate(rng, behandlung_datum)
            plz_prefix = rng.choice(clinic.plz_prefixes)
            kunden_plz = f"{plz_prefix}{rng.randint(0, 999):03d}"
            mitarbeiter = rng.choice(clinic.vets)
            kurzbericht = rng.choice(KURZBERICHT)

            lines_per_invoice = rng.randint(1, 8)
            treatment_num += 1
            bezahlt = "JA" if rng.random() > 0.08 else "NEIN"
            berechnet = "JA"

            for _ in range(lines_per_invoice):
                artikel_typ = rng.choices(
                    ARTIKEL_TYP, weights=[0.5, 0.15, 0.25, 0.1]
                )[0]
                gruppe, got_num = rng.choice(ARTIKEL_GRUPPE[artikel_typ])
                brand = rng.choice(BRAND_BY_GRUPPE.get(gruppe, ["Mp"]))

                menge = rng.choices(
                    [0, 1, 2, 3, 5, 10, 20, 30, 50],
                    weights=[0.1, 0.35, 0.2, 0.1, 0.1, 0.05, 0.04, 0.03, 0.03],
                )[0]
                faktor = round(rng.gauss(clinic.faktor_strategy, 0.3), 2) if artikel_typ == "Leistungen" else ""
                if isinstance(faktor, float):
                    faktor = max(1.0, min(4.0, faktor))

                base_price = {
                    "Leistungen": rng.uniform(15, 80),
                    "Angewandt": rng.uniform(0.5, 15),
                    "Abgegeben": rng.uniform(1, 40),
                    "Artikel": rng.uniform(2, 15),
                }[artikel_typ]
                betrag = round(base_price * (faktor if isinstance(faktor, float) else 1.0), 2)
                umsatz = round(betrag * max(menge, 1) * rng.uniform(0.9, 1.1), 2) if menge else 0.0

                w.writerow(
                    [
                        rechnungsnummer,
                        de_date(behandlung_datum),
                        de_date(rechnungsdatum),
                        artikel_typ,
                        gruppe,
                        got_num,
                        tierart,
                        mitarbeiter,
                        kurzbericht,
                        brand,
                        kunden_plz,
                        f"{umsatz:.2f}",
                        clinic.standort,
                        de_date(geburt),
                        rasse,
                        1,
                        1,
                        f"{betrag:.2f}",
                        menge,
                        f"{faktor:.2f}" if isinstance(faktor, float) else "",
                        treatment_num,
                        berechnet,
                        bezahlt,
                    ]
                )
    return out_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--invoices", type=int, default=2000)
    p.add_argument("--clinics", type=int, default=12)
    p.add_argument("--out", type=Path, default=Path("synthetic_data/out/smartemis_lineitems.csv"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    out = generate(args.invoices, args.clinics, args.out, args.seed)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
