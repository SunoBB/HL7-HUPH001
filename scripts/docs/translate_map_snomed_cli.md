# `translate_map_snomed_cli.py`

Script CLI chạy trực tiếp, không cần FastAPI.

## Chức năng

- nhận tiếng Việt y khoa
- dịch sơ bộ sang tiếng Anh y khoa
- trích xuất các thuật ngữ chính
- gọi Snowstorm local để map sang SNOMED CT
- in ra JSON kết quả

## Cách chạy

```bash
cd /home/suno/Downloads/HL7
python3 scripts/translate_map_snomed_cli.py --text "Bệnh nhân đau ngực, khó thở và sốt"
```

In đẹp:

```bash
python3 scripts/translate_map_snomed_cli.py \
  --text "Bệnh nhân có tiền sử tăng huyết áp và đái tháo đường type 2" \
  --pretty
```

Đọc từ file:

```bash
python3 scripts/translate_map_snomed_cli.py --file note_vi.txt --pretty
```

Pipe:

```bash
echo "Bệnh nhân ho khạc đờm vàng, sốt, khó thở" | \
python3 scripts/translate_map_snomed_cli.py --pretty
```

## Biến môi trường

- `SNOMED_BASE_URL` mặc định `http://localhost:8080`
- `SNOMED_BRANCH` mặc định `MAIN`
- `SNOMED_SEARCH_LIMIT` mặc định `5`
- `SNOMED_TIMEOUT` mặc định `20`

Ví dụ:

```bash
SNOMED_BASE_URL=http://localhost:8080 \
SNOMED_BRANCH=MAIN \
python3 scripts/translate_map_snomed_cli.py --text "Bệnh nhân viêm phổi"
```
