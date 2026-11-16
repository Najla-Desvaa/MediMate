# 💊 MediMate

**Aplikasi Pengelolaan Obat dan Pemantauan Jadwal Konsumsi Berbasis Python**

MediMate merupakan aplikasi berbasis Python yang dikembangkan untuk membantu pengguna mengelola informasi obat, mengatur jadwal konsumsi harian, mencatat riwayat penggunaan obat, memantau persediaan, serta mengidentifikasi obat yang mendekati tanggal kedaluwarsa.

Aplikasi ini mendukung penggunaan dalam bahasa Indonesia dan bahasa Inggris, serta menyediakan pengaturan zona waktu WIB, WITA, dan WIT. Pengembangan MediMate menggunakan **Gradio** untuk antarmuka pengguna, **SQLite** untuk pengelolaan basis data, **pandas** untuk pengolahan data, dan **matplotlib** untuk visualisasi. Seluruh proses pengelolaan obat menggunakan pemrograman berbasis aturan tanpa penerapan *machine learning*.

## 1. Cara Menjalankan Aplikasi melalui Google Colab

MediMate dapat dijalankan melalui Jupyter Notebook yang terintegrasi dengan repositori GitHub.

1. Buka berkas `Launch_App.ipynb` dari repositori GitHub menggunakan Google Colab.
2. Pastikan variabel `GITHUB_REPO` pada sel kode pertama telah mengarah ke alamat repositori MediMate.
3. Pilih menu **Runtime → Run all** untuk menjalankan seluruh sel secara otomatis.
4. Sistem akan mengambil kode sumber terbaru dari GitHub, menginstal pustaka yang diperlukan, menjalankan pengujian, dan mengaktifkan aplikasi.
5. Aplikasi akan mencoba membuka halaman baru pada browser. Apabila browser memblokir pembukaan tab otomatis, gunakan tautan **Open MediMate** yang ditampilkan.

Setiap kali notebook dijalankan ulang, sistem mengambil kode sumber terbaru dari cabang utama repositori GitHub. Dengan demikian, perubahan yang telah disimpan melalui *commit* dapat diterapkan tanpa perlu memperbarui kode sumber secara manual di Google Colab.

### Penyimpanan Data

MediMate menggunakan basis data SQLite untuk menyimpan informasi obat, jadwal, persediaan, dan riwayat konsumsi berdasarkan identitas pengguna.

Selama aplikasi berjalan melalui Google Colab, data disimpan pada direktori `/content/MediMate-records/`, yang terpisah dari direktori kode sumber.

Penyimpanan tersebut bersifat sementara dan mengikuti masa aktif runtime Google Colab. Oleh karena itu, fitur **Analytics & Backup** disediakan untuk mengekspor dan memulihkan data antarsesi.

Identifikasi pengguna dilakukan melalui nama lengkap tanpa kata sandi. Mekanisme tersebut digunakan untuk memilih catatan pengguna, bukan sebagai sistem autentikasi privat. Penggunaan data pasien yang dapat diidentifikasi tidak dianjurkan pada tautan Gradio publik.

## 2. Cara Menjalankan Aplikasi secara Lokal

Selain melalui Google Colab, MediMate dapat dijalankan pada komputer yang telah terpasang Python.

Instal pustaka yang diperlukan melalui terminal:

```bash
pip install -r requirements.txt
```

Kemudian jalankan aplikasi:

```bash
python app.py
```

## 3. Fitur Utama Aplikasi

| Fitur | Deskripsi |
|---|---|
| **Dashboard** | Menampilkan ringkasan jadwal konsumsi harian, status pencatatan, persediaan obat, dan peringatan kedaluwarsa. |
| **My Medicines (Obat Saya)** | Menambahkan, menampilkan, dan memperbarui informasi obat beserta persediaan awal. |
| **Schedule (Jadwal)** | Mengatur jumlah obat per konsumsi, frekuensi harian, waktu konsumsi, serta periode penggunaan. |
| **Intake Tracker (Catatan Konsumsi)** | Mencatat status konsumsi secara terpisah pada setiap jadwal dan menampilkan riwayat berdasarkan zona waktu terpilih. |
| **Inventory (Persediaan)** | Memantau jumlah obat, batch, tanggal kedaluwarsa, dan pengelolaan stok menggunakan prinsip FEFO. |
| **Analytics & Backup** | Menampilkan analisis pencatatan konsumsi, visualisasi data, serta menyediakan fitur pencadangan dan pemulihan basis data. |

## 4. Mekanisme Pengelolaan Jadwal Konsumsi Obat

Pengelolaan jadwal dilakukan melalui dua tahapan utama.

### A. Pendaftaran Informasi Obat

Melalui menu **My Medicines**, pengguna dapat memasukkan informasi dasar obat, meliputi nama obat, bentuk sediaan, kekuatan yang tercantum pada kemasan, jumlah persediaan awal, tanggal kedaluwarsa, serta catatan tambahan.

### B. Pengaturan Jadwal Konsumsi

Melalui menu **Schedule**, pengguna dapat menentukan:

- Jumlah unit obat dalam satu kali konsumsi.
- Frekuensi konsumsi harian, antara 1 hingga 6 kali.
- Waktu konsumsi untuk setiap jadwal dalam format HH:MM.
- Tanggal mulai dan tanggal berakhirnya jadwal, apabila diperlukan.

Sebagai contoh, pengguna memasukkan jadwal penggunaan satu tablet sebanyak dua kali sehari, yaitu pukul 08.00 dan 20.00.

| Waktu | Status Pencatatan | Perubahan Stok |
|---|---|---|
| 08.00 | Sudah diminum | Berkurang sesuai jumlah yang dicatat |
| 20.00 | Belum dicatat | Tidak berubah |

Setiap waktu konsumsi disimpan sebagai jadwal tersendiri dalam basis data. Dengan demikian, pencatatan pada satu waktu tidak memengaruhi status konsumsi pada waktu lainnya.

Pengguna dapat memilih status **Diminum**, **Dilewati**, atau **Hapus Catatan** untuk setiap jadwal. Sistem juga mencegah pengurangan stok berulang akibat pencatatan status yang sama.

Apabila catatan konsumsi dibatalkan, sistem akan mengembalikan alokasi persediaan yang sebelumnya digunakan. Perubahan atau pengarsipan jadwal tidak menghapus riwayat konsumsi yang telah tersimpan.

Seluruh jumlah dan jadwal konsumsi dimasukkan berdasarkan petunjuk penggunaan yang telah dimiliki pengguna. MediMate tidak menentukan dosis maupun meresepkan penggunaan obat secara otomatis.

## 5. Struktur Proyek

```text
MediMate/
├── Launch_App.ipynb
├── app.py
├── database.py
├── medimate_core.py
├── requirements.txt
├── .gitignore
├── tests/
│   └── test_core.py
├── README.md
└── PRESENTATION_GUIDE.md
```

Penjelasan fungsi setiap berkas:

| Berkas | Fungsi |
|---|---|
| `Launch_App.ipynb` | Notebook untuk mengambil kode sumber dari GitHub dan menjalankan aplikasi melalui Google Colab. |
| `app.py` | Mengelola antarmuka Gradio, navigasi, komponen interaktif, dan komunikasi dengan fungsi aplikasi. |
| `database.py` | Mengelola penyimpanan SQLite, informasi pengguna, jadwal, persediaan, dan transaksi konsumsi. |
| `medimate_core.py` | Menyediakan fungsi validasi, pengolahan tanggal dan waktu, serta aturan dasar aplikasi. |
| `requirements.txt` | Memuat daftar pustaka Python yang diperlukan untuk menjalankan aplikasi. |
| `.gitignore` | Menentukan berkas lokal yang tidak disertakan dalam pelacakan Git. |
| `tests/test_core.py` | Memuat pengujian otomatis terhadap fungsi dan logika aplikasi. |
| `README.md` | Menyediakan dokumentasi utama proyek. |
| `PRESENTATION_GUIDE.md` | Menyediakan panduan penjelasan dan demonstrasi aplikasi. |

## 6. Pengujian Sistem

Pengujian otomatis dilakukan untuk mengevaluasi fungsi utama aplikasi, termasuk:

- Penambahan dan perubahan informasi obat.
- Pengaturan beberapa jadwal konsumsi dalam satu hari.
- Pencatatan status konsumsi secara independen.
- Pengurangan dan pengembalian persediaan.
- Pencegahan pencatatan ganda.
- Validasi input dan konflik jadwal.
- Konversi waktu pencatatan berdasarkan WIB, WITA, dan WIT.
- Pengurutan riwayat berdasarkan waktu pencatatan.
- Pencadangan dan pemulihan basis data.
- Pemilihan catatan pengguna berdasarkan nama lengkap.

Pengujian dapat dijalankan melalui terminal menggunakan perintah:

```bash
python -m unittest discover -s tests -v
```

## 7. Desain Antarmuka

MediMate menerapkan desain antarmuka bertema **strawberry-cream** dengan kombinasi warna merah muda, lavender, mint, dan peach.

Antarmuka dirancang dengan tata letak terpusat, tombol interaktif dengan efek *hover*, serta penggunaan warna teks yang kontras untuk meningkatkan keterbacaan.

Aplikasi juga menyediakan tombol pengalihan bahasa **Indonesia/English (ID/EN)** dan tiga pilihan zona waktu Indonesia, yaitu **WIB (UTC+7), WITA (UTC+8), dan WIT (UTC+9)**.

## 8. Kesimpulan

MediMate dikembangkan sebagai penerapan pemrograman Python dalam bidang farmasi, khususnya untuk mendukung pengelolaan obat secara mandiri dan terstruktur.

Melalui integrasi antarmuka interaktif, basis data, pengolahan jadwal, pencatatan konsumsi, serta visualisasi informasi, aplikasi ini menunjukkan pemanfaatan teknologi komputasi untuk membantu aktivitas pengelolaan obat sehari-hari.
