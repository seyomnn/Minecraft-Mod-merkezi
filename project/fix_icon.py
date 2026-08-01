from PIL import Image

img = Image.open("ikon.ico").convert("RGBA")

img.save("ikon.ico", format="ICO", sizes=[
    (16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
])

print("ikon.ico oluşturuldu!")
