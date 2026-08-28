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

Production có thể dùng PM2 để chạy lại lệnh `run` sau mỗi chu kỳ. Airflow và
Cloud Composer vẫn được để lại cho phase triển khai sau.

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

## Chạy định kỳ bằng PM2 trên Ubuntu

Project dùng PM2 như một process supervisor, không dùng `cron_restart`. Mỗi lần
`run_traffic_tracking.sh` kết thúc, PM2 đợi 120 giây rồi mới chạy chu kỳ tiếp
theo. Vì vậy khoảng cách giữa hai lần bắt đầu bằng thời gian xử lý của chu kỳ
trước cộng thêm 2 phút. PM2 chỉ chạy một instance; PostgreSQL advisory lock vẫn
ngăn một lệnh thủ công khác xử lý đồng thời.

### 1. Chuẩn bị Ubuntu

Cài Docker Engine trước, sau đó bảo đảm deploy user có thể gọi Docker mà không
cần `sudo`:

```bash
sudo usermod -aG docker "$USER"
```

Đăng xuất rồi đăng nhập lại để group mới có hiệu lực. Quyền thành viên group
`docker` tương đương quyền quản trị máy, vì vậy chỉ cấp cho deploy user tin cậy.

Cài Node.js, npm và PM2. Nên dùng một bản Node.js LTS còn được hỗ trợ:

```bash
sudo apt update
sudo apt install -y nodejs npm
sudo npm install -g pm2

node --version
pm2 --version
docker version
```

### 2. Chuẩn bị database và Docker image

Tại thư mục project, tạo `.env`, áp dụng DDL từ host và build image CPU:

```bash
cp .env.example .env
# Điền credentials và cấu hình production vào .env

python main.py migrate
docker build --target cpu -t traffic-tracking:cpu .
```

Nếu PostgreSQL chạy trên chính Ubuntu host, đặt giá trị sau trong `.env`:

```env
DB_SERVER=host.docker.internal
```

Kiểm tra một chu kỳ thủ công trước khi giao cho PM2:

```bash
./run_traffic_tracking.sh
```

Runner dùng image `traffic-tracking:cpu`, đọc `.env` bằng đường dẫn tuyệt đối,
mount `photo/` vào container và chạy Docker ở foreground. Có thể override image
hoặc env file khi kiểm thử:

```bash
TRAFFIC_TRACKING_IMAGE=traffic-tracking:cpu-yolo26s \
TRAFFIC_TRACKING_ENV_FILE=/path/to/runtime.env \
./run_traffic_tracking.sh
```

### 3. Khởi động lịch PM2

```bash
pm2 start ecosystem.config.cjs
pm2 status
pm2 describe traffic-tracking
pm2 logs traffic-tracking --lines 200
```

`ecosystem.config.cjs` cấu hình một instance, delay 120.000 ms, và cho process
tối đa 90 giây để dừng. Nếu runner lỗi trong vòng 30 giây liên tục 10 lần, PM2
chuyển app sang trạng thái lỗi để tránh retry vô hạn với cấu hình hoặc image bị
sai. Sau khi sửa nguyên nhân, chạy `pm2 restart traffic-tracking`.

### 4. Tự khởi động sau khi Ubuntu reboot

Chạy bằng chính deploy user đang quản lý application, không chạy PM2 bằng root:

```bash
pm2 startup systemd
```

PM2 sẽ in ra một câu lệnh `sudo ...`; copy và chạy chính xác câu lệnh đó, sau
đó lưu danh sách process hiện tại:

```bash
pm2 save
```

Kiểm tra systemd unit mà PM2 vừa tạo:

```bash
systemctl status "pm2-$USER"
```

### 5. Vận hành và cập nhật

```bash
# Xem log và trạng thái
pm2 logs traffic-tracking --lines 200
pm2 status

# Tạm dừng hoặc chạy lại
pm2 stop traffic-tracking
pm2 restart traffic-tracking

# Xóa hẳn khỏi PM2
pm2 delete traffic-tracking
pm2 save
```

Sau khi cập nhật source hoặc Dockerfile, build lại image rồi nạp lại cấu hình:

```bash
docker build --target cpu -t traffic-tracking:cpu .
pm2 startOrRestart ecosystem.config.cjs
pm2 save
```

PM2 ghi log dưới `~/.pm2/logs`. Nên bật rotation để log không tăng vô hạn:

```bash
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 100M
pm2 set pm2-logrotate:retain 14
pm2 set pm2-logrotate:compress true
pm2 save
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

## Các loại trạng thái

Project có ba cột `status` thuộc ba nhóm dữ liệu khác nhau. Không nên so sánh
hoặc diễn giải các nhóm này như cùng một enum.

### Trạng thái observation

`traffic_tracking.observations.status` cho biết kết quả xử lý một camera trong
một chu kỳ:

- `succeeded`: tải ảnh và chạy YOLO thành công. Các cột số lượng phương tiện có
  giá trị, kể cả khi tất cả đều bằng `0`.
- `duplicate`: checksum ảnh và inference signature giống observation gần nhất;
  pipeline không chạy YOLO lại mà sao chép counts và detections, đồng thời ghi
  observation nguồn vào `duplicate_of_id`.
- `skipped_not_up`: camera có trạng thái upstream khác `UP`, nên không tải ảnh
  và không chạy YOLO.
- `fetch_error`: không tải hoặc không xác thực được ảnh camera hợp lệ.
- `inference_error`: tải ảnh thành công nhưng YOLO xử lý ảnh thất bại.

Các observation `skipped_not_up`, `fetch_error` và `inference_error` có các cột
count bằng `NULL`, không phải bằng `0`.

### Photo path và thông tin lỗi của observation

Hai cột `original_photo_path` và `annotated_photo_path` chỉ có giá trị khi
`SAVE_IMAGES=true` và pipeline lưu ảnh thành công:

| Observation status | Photo path | Error |
| --- | --- | --- |
| `succeeded` | Có cả đường dẫn ảnh gốc và ảnh annotated khi bật lưu ảnh; nếu `SAVE_IMAGES=false` thì cả hai là `NULL`. | Thông thường `error_code` và `error_message` là `NULL`. |
| `duplicate` | Có đường dẫn của hai ảnh được lưu cho observation hiện tại khi bật lưu ảnh; không tái sử dụng path của observation cũ. | Thông thường `error_code` và `error_message` là `NULL`. |
| `skipped_not_up` | Cả hai là `NULL` vì pipeline không tải ảnh. | `error_code='camera_not_up'`; message chứa trạng thái upstream. |
| `fetch_error` | Cả hai là `NULL` vì không có ảnh hợp lệ để lưu. | `error_code` thường là `http_error` hoặc `invalid_snapshot`; message chứa lỗi HTTP, content type hoặc lỗi giải mã ảnh. |
| `inference_error` | Cả hai là `NULL` theo implementation hiện tại, kể cả khi đã tải được ảnh gốc. | `error_code='inference_error'`; message chứa lỗi từ YOLO. |

Với `PHOTO_DIR=photo` mặc định, photo path được lưu dưới dạng đường dẫn tương
đối như
`photo/<run-id>/<camera-id>_<timestamp>_original.jpg` và
`photo/<run-id>/<camera-id>_<timestamp>_annotated.jpg`. Trong Docker/PM2,
thư mục `photo/` được bind mount ra host để file không mất khi container
`--rm` kết thúc.

`error_code` dùng để lọc theo loại lỗi; `error_message` phục vụ chẩn đoán và có
thể thay đổi theo HTTP client, Pillow hoặc YOLO. Không dùng `error_message` như
một enum ổn định. Bảng `traffic_tracking.runs` chỉ có `error_message`, thường
có giá trị khi run ở trạng thái `failed`. Lỗi riêng từng camera được ghi tại
observation; run sẽ là `partial`, hoặc `failed` nếu không camera `UP` nào tạo
được kết quả thành công/duplicate.

### Trạng thái run

`traffic_tracking.runs.status` cho biết kết quả của toàn bộ một lần chạy:

- `running`: run đã được tạo và vẫn đang xử lý.
- `completed`: command kết thúc thành công theo quy tắc của loại run. Với
  `run`, trạng thái này có nghĩa không có camera nào bị lỗi.
- `partial`: một `run` hoàn tất nhưng có ít nhất một camera bị lỗi; kết quả của
  các camera còn lại vẫn được lưu.
- `failed`: lỗi hệ thống làm command không thể hoàn tất, hoặc một `run` có
  camera `UP` nhưng không camera nào tạo được observation `succeeded` hay
  `duplicate`.

### Trạng thái camera

`traffic_tracking.cameras.status` được đồng bộ trực tiếp từ `CamStatus` của
website giao thông TP.HCM và không phải enum do project kiểm soát. Các giá trị
đang quan sát được gồm:

- `UP`: camera sẵn sàng; pipeline tải ảnh và chạy YOLO.
- `NOT_IMAGE`: upstream không cung cấp feed ảnh hợp lệ; pipeline ghi
  `skipped_not_up` và bỏ qua inference.

Website có thể bổ sung giá trị mới. Pipeline chỉ xử lý inference khi trạng thái
chính xác là `UP`; mọi giá trị khác, kể cả `NULL`, đều được xem là không sẵn
sàng.

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
