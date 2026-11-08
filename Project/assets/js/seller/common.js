// seller/common.js: hàm dùng chung cho các trang quản lý của Seller (shop.html, product-edit.html).
// Nạp SAU core/api.js. Các trang không được khai báo lại những tên dưới đây.

const STATUS_LABEL = {
  approved: "Đã đăng",
  pending: "Chờ Admin duyệt",
  blocked: "Bị chặn",
  rejected: "Bị từ chối",
};

function money(n) {
  return Number(n).toLocaleString("vi-VN") + " VNĐ";
}

let toastTimer = null;
function showToast(msg) {
  const el = document.getElementById("sellerToast");
  el.innerText = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 4000);
}

function signOut(e) {
  if (e) e.preventDefault();
  clearSession();
  window.location.href = LOGIN_PAGE;
}

// Hết phiên (401) thì về trang đăng nhập. Tài khoản bị khóa (403) thì báo rồi đăng xuất. Lỗi khác báo bằng toast
function handleError(err) {
  if (err.status === 401) {
    window.location.href = LOGIN_PAGE;
    return;
  }
  showToast(err.message);
  if (err.code === "ACCOUNT_BANNED") setTimeout(signOut, 2500);
}

// Điền tên shop, email, chữ cái đầu vào thanh đầu trang
function fillSellerHeader(me, shop) {
  document.getElementById("sellerEmailHeader").innerText = me.email;
  if (!shop) return;
  const initials = (shop.name || "SH").trim().slice(0, 2).toUpperCase();
  document.getElementById("shopNameHeader").innerText = shop.name;
  document.getElementById("avatarBtn").innerText = initials;
  document.getElementById("dropdownAvatar").innerText = initials;
}

// Hộp thông báo kết quả kiểm duyệt của AI Detector: { decision, risk_score, reasons[], account? }
function moderationHtml(m, subject) {
  if (!m) return "";
  const reasons = (m.reasons || [])
    .map((r) => `<li>${escapeHtml(r.detail)} (+${r.points})</li>`)
    .join("");
  let html;
  if (m.decision === "approved") {
    html = `<div class="result-box ok"><b>Đã đăng.</b> ${escapeHtml(subject)} đã qua kiểm duyệt tự động và hiển thị với người mua.</div>`;
  } else if (m.decision === "pending") {
    html = `<div class="result-box warn"><b>Đang chờ Admin duyệt</b> (điểm rủi ro ${m.risk_score}/100). ${escapeHtml(subject)} chưa hiển thị với người mua.<ul>${reasons}</ul></div>`;
  } else if (m.decision === "rejected") {
    html = `<div class="result-box bad"><b>Admin đã từ chối.</b> ${escapeHtml(subject)} không hiển thị. Chỉnh sửa rồi lưu để gửi duyệt lại.<ul>${reasons}</ul></div>`;
  } else {
    html = `<div class="result-box bad"><b>Bị chặn</b> (điểm rủi ro ${m.risk_score}/100). ${escapeHtml(subject)} không hiển thị với người mua.<ul>${reasons}</ul></div>`;
  }
  if (m.account) {
    html +=
      m.account.action === "ban"
        ? `<div class="result-box bad"><b>Tài khoản đã bị khóa</b> vì có ${m.account.blocked_count} mục bị chặn trong 7 ngày. Liên hệ Admin để được xem xét.</div>`
        : `<div class="result-box warn"><b>Cảnh báo:</b> bạn có ${m.account.blocked_count} mục bị chặn trong 7 ngày gần nhất. Từ 3 mục trở lên tài khoản sẽ bị khóa.</div>`;
  }
  return html;
}
