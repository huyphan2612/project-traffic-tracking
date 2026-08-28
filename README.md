# Đếm phương tiện từ camera giao thông

Pipeline Python 3.10 dùng để đồng bộ thông tin camera giao thông TP.HCM, tải ảnh
hiện tại từ camera, đếm phương tiện bằng YOLO26m và lưu kết quả vào
PostgreSQL/PostGIS.

## Cài đặt

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Điền thông tin kết nối PostgreSQL vào `.env`. Không commit file này vào Git.
Máy chạy cần có PostgreSQL client (`psql`) trong `PATH`.

Đối với máy development chỉ dùng CPU, hãy cài PyTorch CPU wheel trước khi cài
`requirements.txt`. Trên GPU server production, hãy cài PyTorch wheel tương
thích với phiên bản CUDA của server trước; Ultralytics sẽ sử dụng bản PyTorch
đã cài.

## Các câu lệnh

### 1. Tạo hoặc cập nhật cấu trúc database

```bash
python main.py migrate
```

Gọi `psql` để áp dụng file DDL hiện tại tại `migrations/schema.sql`, sử dụng
thông tin kết nối PostgreSQL trong `.env`. DDL chạy trong một transaction, dừng
ngay khi có lỗi và có thể chạy lặp lại an toàn. Khi khởi tạo database mới, cần
chạy lệnh này trước các lệnh còn lại.

Lệnh sẽ tạo hoặc cập nhật schema `traffic_tracking` và bốn bảng nghiệp vụ:

- `cameras`: thông tin và trạng thái camera.
- `runs`: thông tin từng lần chạy pipeline.
- `observations`: ảnh chụp, kết quả nhận diện và số lượng phương tiện.
- `benchmarks`: kết quả đo hiệu năng tải ảnh và YOLO.

Project không dùng hệ thống versioned migration hoặc rollback. Khi thay đổi
schema, hãy chạy câu lệnh `ALTER` tương ứng trên database hiện tại bằng `psql`,
sau đó cập nhật `migrations/schema.sql` để file luôn phản ánh cấu trúc đầy đủ
dùng cho database mới.

### 2. Đồng bộ danh sách camera

```bash
python main.py sync-cameras
```

Lấy toàn bộ camera đã được publish từ website giao thông TP.HCM, sau đó thêm mới
hoặc cập nhật vào bảng `traffic_tracking.cameras`.

Dữ liệu được đồng bộ bao gồm trạng thái camera, tên giao lộ/tên hiển thị, tọa
độ, các trường đã chuẩn hóa và toàn bộ metadata gốc dưới dạng JSONB. Lệnh này
không tải ảnh camera và không chạy YOLO.

### 3. Đo hiệu năng tải ảnh và YOLO

```bash
python main.py benchmark --sample-size 50
```

Chọn xác định 50 camera có trạng thái `UP`, sau đó thực hiện:

- Đo tốc độ tải ảnh với mức concurrency 1, 2 và 4.
- Đo hiệu năng YOLO với kích thước ảnh đầu vào 640 và 1280.
- Thử các batch size 1, 2 và 4.
- Ghi thông tin máy chạy và kết quả vào `traffic_tracking.runs` và
  `traffic_tracking.benchmarks`.

Benchmark không tạo dữ liệu quan sát giao thông chính thức trong bảng
`observations`. Có thể thay số `50` bằng kích thước mẫu khác.

### 4. Chạy một chu kỳ đếm phương tiện hoàn chỉnh

```bash
python main.py run
```

Đây là câu lệnh chính của pipeline. Mỗi lần gọi sẽ chạy một chu kỳ duy nhất:

1. Đồng bộ metadata và trạng thái camera mới nhất.
2. Ghi nhận trạng thái bỏ qua đối với camera không ở trạng thái `UP`.
3. Tải một ảnh hiện tại từ mỗi camera `UP`.
4. Tính checksum SHA-256 của ảnh.
5. Chạy YOLO nếu ảnh là ảnh mới.
6. Lưu danh sách detection, số lượng phương tiện, thời gian xử lý và thông tin
   model vào `traffic_tracking.observations`.

Nếu checksum trùng với ảnh gần nhất, pipeline vẫn tạo observation mới nhưng
liên kết với observation trước đó, sử dụng lại kết quả đếm và không chạy YOLO
lần nữa.

Lỗi tải ảnh hoặc lỗi inference của từng camera cũng được lưu vào database và
không làm dừng toàn bộ chu kỳ.

Trước khi inference, pipeline tự động loại bỏ phần canvas đen bao quanh và chỉ
đưa vùng video thật vào YOLO. Khi `SAVE_IMAGES=true`, lệnh lưu ảnh gốc nguyên
canvas và ảnh annotated đã crop vào `photo/<run-id>/`. Khi `SAVE_IMAGES=false`,
ảnh chỉ được giữ trong bộ nhớ trong thời gian xử lý.

Thứ tự khuyến nghị khi thiết lập lần đầu:

```text
migrate -> sync-cameras -> benchmark -> run
```

Sau khi thiết lập xong, mỗi lần thu thập dữ liệu thủ công thường chỉ cần chạy:

```bash
python main.py run
```

Scheduling và Airflow được để lại cho phase triển khai sau.

## Docker

Docker image chỉ dùng để chạy `sync-cameras`, `benchmark` và `run`. Image không
chứa `psql` hoặc `migrations/schema.sql`, vì vậy cần tạo schema từ host trước:

```bash
python main.py migrate
```

Build image CPU để chạy local:

```bash
docker build --target cpu -t traffic-tracking:cpu .
```

Build image GPU cho NVIDIA server:

```bash
docker build --target gpu -t traffic-tracking:gpu .
```

Cả hai target mặc định tải và đóng gói `yolo26m.pt` trong lúc build. Có thể đổi
model bằng build argument, ví dụ:

```bash
docker build --target cpu \
  --build-arg YOLO_MODEL=yolo26s.pt \
  -t traffic-tracking:cpu-yolo26s .
```

Chạy một chu kỳ bằng CPU:

```bash
docker run --rm --env-file .env traffic-tracking:cpu run
```

Chạy bằng GPU:

```bash
docker run --rm --gpus all --env-file .env traffic-tracking:gpu run
```

GPU server phải cài NVIDIA driver, NVIDIA Container Toolkit và cấu hình Docker
runtime. `YOLO_DEVICE=auto` sẽ chọn `cuda:0` khi GPU được truyền vào container.

Khi `SAVE_IMAGES=true`, mount thư mục ảnh để dữ liệu không mất khi container
kết thúc:

```bash
docker run --rm --env-file .env \
  -v "$PWD/photo:/app/photo" \
  traffic-tracking:cpu run
```

Nếu PostgreSQL chạy trực tiếp trên Docker host, `localhost` bên trong container
không trỏ về host. Đặt `DB_SERVER=host.docker.internal` và chạy thêm:

```bash
docker run --rm --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  traffic-tracking:cpu run
```

## Lưu ảnh khi development

Đặt biến môi trường sau để lưu ảnh gốc và ảnh đã được YOLO đánh dấu của mọi
camera được xử lý:

```env
SAVE_IMAGES=true
PHOTO_DIR=photo
AUTO_CROP=true
```

Ảnh được lưu tại `photo/<run-id>/`. Nội dung thư mục này đã được Git-ignore và
không được tự động dọn dẹp. Một lần chạy đầy đủ có thể tạo hơn 1.400 file, vì
vậy cần theo dõi dung lượng ổ đĩa trong môi trường development.

Mặc định `SAVE_IMAGES=false`; dữ liệu ảnh chỉ tồn tại trong bộ nhớ trong thời
gian xử lý và không được lưu vĩnh viễn.

## Cách tính số phương tiện

Mỗi observation là số phương tiện xuất hiện trong một ảnh tại thời điểm chụp,
không phải số phương tiện duy nhất đã đi qua giao lộ trong một khoảng thời gian.

Các nhóm phương tiện được lưu gồm:

- `bicycle`: xe đạp.
- `car`: xe hơi.
- `motorcycle`: xe máy.
- `bus`: xe buýt.
- `truck`: xe tải.
- `other_vehicle`: tổng của `bicycle + bus + truck`.
- `total_vehicle`: tổng của cả năm class phương tiện.

YOLO26m sử dụng trọng số COCO pretrained làm baseline với cấu hình mặc định
`YOLO_IMGSZ=1280` và `YOLO_CONFIDENCE=0.15`. Cần kiểm tra license của
Ultralytics trước khi sử dụng thương mại. Phiên bản v1 chưa cam kết độ chính
xác và chưa bao gồm fine-tuning model theo góc nhìn camera giao thông TP.HCM.

Checksum ảnh chỉ được tái sử dụng khi toàn bộ inference signature (model
weights, phiên bản Ultralytics, image size, confidence, class IDs và phiên bản
preprocessing) không thay đổi. Vì vậy, khi đổi model hoặc cấu hình, ảnh trùng
vẫn được chạy YOLO lại thay vì sao chép kết quả cũ.

## Kiểm thử

```bash
source .venv/bin/activate
pytest -q
```

Xem [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) để biết checklist đã hoàn
thành và các hạng mục triển khai được để lại cho phase sau.
