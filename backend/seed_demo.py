"""Seed a demo notebook (run while the server is up). NOT auto-run on purpose:
the workspace stays empty by default; run this when you want sample content.

Usage:  cd backend && python seed_demo.py [http://localhost:8000]
"""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

SOURCES = [
    ("Photosynthesis basics", (
     "Photosynthesis is the process by which green plants convert sunlight, water and carbon dioxide "
     "into glucose and oxygen. Chlorophyll in chloroplasts captures light energy. The light-dependent "
     "reactions occur in the thylakoid membranes and produce ATP and NADPH. The Calvin cycle then fixes "
     "carbon dioxide into sugar in the stroma." )),
    ("Factors affecting photosynthesis", (
     "The rate of photosynthesis depends on light intensity, carbon dioxide concentration, and temperature. "
     "At low light, raising intensity boosts the rate linearly. Beyond the saturation point, extra light "
     "gives no further gain. High temperatures denature the enzymes of the Calvin cycle and slow the process." )),
    ("Why leaves are green", (
     "Leaves look green because chlorophyll absorbs red and blue light but reflects green wavelengths. "
     "In autumn, chlorophyll breaks down and hidden yellow and orange carotenoid pigments become visible. "
     "Some trees also produce red anthocyanins as a sunscreen for the retreating nutrients." )),
]

def main():
    nb = httpx.post(f"{BASE}/api/notebooks", json={"title": "Demo: Photosynthesis"}).json()
    print("notebook:", nb["id"], "-", nb["title"])
    for title, text in SOURCES:
        s = httpx.post(f"{nb['id'] and BASE}/api/notebooks/{nb['id']}/sources:paste",
                       json={"title": title, "text": text}).json()
        print("  source:", s["title"], f"({s['word_count']} words)")
    print(f"\nOpen {BASE} and try: 'Where do the light-dependent reactions occur?'")



if __name__ == "__main__":
    main()
