
import base64

with open("/Users/vijaykrishnan.kumar/Desktop/form1-k.pdf", "rb") as f:

    original = f.read()

b64 = base64.b64encode(original).decode()

b64_clean = b64.strip().replace("\n","").replace("\r","").replace(" ","")

decoded = base64.b64decode(b64_clean)

print("Match:", original == decoded)

print("Original size:", len(original))

print("Decoded size:", len(decoded))

