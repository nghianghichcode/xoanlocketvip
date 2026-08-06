# Thanh toán tự động VietQR + SePay

Ứng dụng tạo một mã đơn duy nhất dạng `XOAN...`, đưa mã này vào nội dung chuyển
khoản của QR, nhận webhook giao dịch vào từ SePay, đối chiếu đúng mã đơn và đúng
số tiền, sau đó tự đánh dấu đơn đã thanh toán. Giao diện kiểm tra trạng thái mỗi
3 giây và tự tiếp tục sau khi ngân hàng xác nhận.

## Biến môi trường trên Railway

Đặt các biến sau trong service chạy ứng dụng:

```env
VIETQR_BANK_BIN=970436
VIETQR_ACCOUNT_NO=SO_TAI_KHOAN_NHAN
VIETQR_ACCOUNT_NAME=TEN CHU TAI KHOAN
SEPAY_WEBHOOK_API_KEY=CHUOI_BI_MAT_DAI_NGAU_NHIEN
PAYMENT_ORDER_PREFIX=XOAN
PAYMENT_UNLOCK_AMOUNT=20000
PAYMENT_UNLOCK_DAYS=7
WEEKLY_USAGE_LIMIT=1
```

Không dùng `SEPAY_PAYMENT_URL_TEMPLATE` và không dùng domain
`sepay.example.com`; đó chỉ là địa chỉ minh hoạ. `VIETQR_BANK_CODE` cũng được hỗ
trợ, nhưng nếu đã có `VIETQR_BANK_BIN` thì không cần thêm.

Nên thêm Railway Postgres và liên kết nó với service để Railway tự cấp
`DATABASE_URL`. Nếu chỉ dùng SQLite, đơn đang chờ có thể mất khi deploy/restart.

## Tạo webhook trên SePay

Trong My SePay, liên kết đúng tài khoản ngân hàng nhận tiền rồi tạo webhook:

- Sự kiện: `Có tiền vào`.
- URL: `https://TEN-MIEN-RAILWAY/api/sepay/webhook`.
- Kiểu chứng thực: `API Key`.
- API Key: đúng bằng `SEPAY_WEBHOOK_API_KEY` trên Railway.
- Request content type: `application/json`.
- Nếu dùng bộ lọc mã thanh toán, đặt tiền tố `XOAN` (hoặc giá trị của
  `PAYMENT_ORDER_PREFIX`).

Sau khi Railway deploy xong, dùng nút **Gửi thử** trong SePay. Endpoint phải trả
HTTP 200 và JSON có `"success": true`. Payload thử chỉ được ghi nhận nếu
`content`/`code` chứa một mã đơn đang chờ thật và `transferAmount` đúng số tiền
của đơn; đây là chủ ý để tránh mở khoá nhầm.

## Kiểm tra giao dịch thật

1. Tạo một đơn trên website và kiểm tra QR hiển thị đúng tài khoản, 20.000đ và
   nội dung là mã `XOAN...`.
2. Quét QR bằng ứng dụng ngân hàng, giữ nguyên số tiền và nội dung.
3. Sau khi SePay nhận biến động số dư, website sẽ đổi trạng thái tự động.
4. Nếu chưa nhận, xem lịch sử webhook trên SePay và deployment logs trên Railway;
   thường nguyên nhân là sai API Key, sai URL, chưa liên kết đúng tài khoản, hoặc
   người chuyển đã sửa nội dung giao dịch.
