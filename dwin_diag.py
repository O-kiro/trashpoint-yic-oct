#!/usr/bin/env python3
"""DWIN display check — why do the numbers on screen stay 0?

Answers two questions:
  1. Do numbers the Pi writes actually arrive in the display's memory?
     (writes a value, then reads the same VP back)
  2. Which VP address does each number on the screen really read?
     (fills a range of VPs with different values — the value you SEE
     tells you the address that field is wired to in the DGUS project)

Stop the service first, it owns the serial port:
    sudo systemctl stop trashpoint-bin
    python3 dwin_diag.py
    sudo systemctl start trashpoint-bin
"""

import time

from dwin_display import (
    PAGE_DEPOSIT,
    PAGE_HOME,
    PAGE_SUMMARY,
    VP_ALUMINUM_COUNT,
    VP_PLASTIC_COUNT,
    VP_TOTAL_POINTS,
    DwinDisplay,
)

PROBE_START = 0x1000
PROBE_COUNT = 32
PROBE_BASE_VALUE = 11  # VP 0x1000 gets 11, 0x1001 gets 12, ... (all 2 digits)


def check_writes(display: DwinDisplay) -> bool:
    print("\n[1] Tulis angka lalu baca balik dari memori layar")
    all_ok = True
    for label, vp, value in (
        ("botol ", VP_PLASTIC_COUNT, 3),
        ("kaleng", VP_ALUMINUM_COUNT, 2),
        ("poin  ", VP_TOTAL_POINTS, 50),
    ):
        display.write_number(vp, value)
        read_back = display.read_vp(vp)
        if read_back == value:
            status = "OK"
        elif read_back is None:
            status = "GAGAL — layar tidak menjawab"
            all_ok = False
        else:
            status = "GAGAL — isi memori beda"
            all_ok = False
        print(f"    {label} VP 0x{vp:04X}: tulis {value}, terbaca {read_back}  -> {status}")
    return all_ok


def probe_addresses(display: DwinDisplay):
    print(f"\n[2] Isi VP 0x{PROBE_START:04X}-0x{PROBE_START + PROBE_COUNT - 1:04X} dengan angka berbeda")
    for i in range(PROBE_COUNT):
        display.write_number(PROBE_START + i, PROBE_BASE_VALUE + i)
    print("    Lihat layar. Cocokkan angka yang tampil dengan tabel ini:")
    for row in range(0, PROBE_COUNT, 8):
        print("    " + "   ".join(
            f"{PROBE_BASE_VALUE + i:>2} = 0x{PROBE_START + i:04X}" for i in range(row, row + 8)
        ))
    print("    (tetap 0 = angka itu membaca alamat di luar rentang ini;")
    print("     angka sangat besar = field itu bertipe 4 byte, bukan 2 byte)")


def main():
    display = DwinDisplay()
    try:
        display.change_page(PAGE_DEPOSIT)
        time.sleep(0.5)
        writes_ok = check_writes(display)
        if writes_ok:
            print("    Pi -> layar BERES. Harusnya di layar tampil: botol 3, kaleng 2, poin 50.")
        else:
            print("    Angka dari Pi TIDAK sampai ke layar (masalah serial/kabel/baud).")
        input("\nCatat angka yang tampil di halaman SETOR, lalu tekan Enter...")

        probe_addresses(display)
        input("\nCatat angka yang tampil di halaman SETOR, lalu tekan Enter...")
        display.change_page(PAGE_SUMMARY)
        input("Sekarang halaman RINGKASAN. Catat angkanya, lalu tekan Enter...")
    finally:
        for i in range(PROBE_COUNT):
            display.write_number(PROBE_START + i, 0)
        display.change_page(PAGE_HOME)
        display.cleanup()
        print("Selesai — layar dikembalikan ke halaman awal.")


if __name__ == "__main__":
    main()
