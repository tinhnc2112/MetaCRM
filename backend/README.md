# FastAPI AI Sale BOT Backend

Tài liệu này hướng dẫn chạy thử backend FastAPI AI Sale BOT trong môi trường local và cấu hình Meta webhook.

## 1. Cài dependencies

Mở terminal tại thư mục `backend`:

```bash
cd backend
```

Cài các dependencies của backend theo file cấu hình hiện có trong project. Ví dụ nếu backend có `requirements.txt`:

```bash
pip install -r requirements.txt
```

Nếu project dùng `pyproject.toml`, hãy cài theo công cụ quản lý package tương ứng của project.

## 2. Cấu hình biến môi trường

Copy file biến môi trường mẫu thành `.env`:

```bash
copy .env.example .env
```

Trên macOS/Linux:

```bash
cp .env.example .env
```

Sau đó mở `.env` và điền giá trị phù hợp:

```env
PAGE_ACCESS_TOKEN=your_page_access_token_here
VERIFY_TOKEN=your_verify_token_here
OPENAI_API_KEY=your_openai_api_key_here
DATABASE_URL=sqlite:///./metacrm.db
OPENAI_MODEL=gpt-4o-mini
```

Lưu ý: không commit secret thật như `PAGE_ACCESS_TOKEN` hoặc `OPENAI_API_KEY` lên repository.

## 3. Chạy backend local

Trong thư mục `backend`, chạy:

```bash
uvicorn main:app --reload
```

Mặc định API sẽ chạy tại:

```text
http://127.0.0.1:8000
```

## 4. Test health check

Gửi request:

```bash
curl http://127.0.0.1:8000/health
```

Hoặc mở trình duyệt/Postman với endpoint:

```text
GET http://127.0.0.1:8000/health
```

Nếu backend chạy đúng, endpoint `/health` sẽ trả về phản hồi health check của ứng dụng.

## 5. Cấu hình Meta webhook

Trong Meta Developer Dashboard, cấu hình webhook cho app/page:

- Callback URL: `https://<public-domain>/webhook`
- Verify token: dùng đúng giá trị `VERIFY_TOKEN` đã cấu hình trong file `.env`

Khi chạy local, Meta cần truy cập được callback URL public. Hãy dùng ngrok hoặc tunnel tương tự để expose server local:

```bash
ngrok http 8000
```

Sau đó dùng URL HTTPS do ngrok cung cấp làm callback URL, ví dụ:

```text
https://your-ngrok-domain.ngrok-free.app/webhook
```

Đảm bảo backend vẫn đang chạy bằng lệnh:

```bash
uvicorn main:app --reload
```

## 6. Ghi chú bảo mật

- Không ghi secret thật vào `.env.example`.
- Không commit file `.env` nếu chứa token/API key thật.
- Chỉ dùng `.env.example` để mô tả các biến môi trường cần thiết.
