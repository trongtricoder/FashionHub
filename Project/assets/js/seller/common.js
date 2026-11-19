// seller/common.js: hàm dùng chung cho các trang quản lý của Seller.
// Nạp SAU core/api.js. Các trang không được khai báo lại những tên dưới đây.

const STATUS_LABEL = {
  approved: "Đã đăng",
  pending: "Chờ Admin duyệt",
  blocked: "Bị chặn",
  rejected: "Bị từ chối",
};

function money(n) {
  const english = window.getSiteLanguage ? getSiteLanguage() === "en" : localStorage.getItem("fashionhub-language") === "en";
  return Number(n).toLocaleString(english ? "en-US" : "vi-VN") + (english ? " VND" : " VNĐ");
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

let sellerNotifications = [];
let sellerNotificationBusy = false;
let sellerOrderNotificationBaseline = false;
const sellerUserId = (getSession() || {}).me?.id || "current";
const sellerReadNotificationsKey = `fashionhub-seller-notifications-read-${sellerUserId}`;
const sellerOrderBaselineKey = `fashionhub-seller-order-notifications-initialized-${sellerUserId}`;
const sellerReadNotificationIds = new Set(
  (localStorage.getItem(sellerReadNotificationsKey) || "").split("\n").filter(Boolean),
);

function persistSellerReadNotifications() {
  localStorage.setItem(sellerReadNotificationsKey, [...sellerReadNotificationIds].join("\n"));
}

function renderSellerNotifications() {
  const list = document.getElementById("sellerNotificationsList");
  if (!list) return;
  list.replaceChildren();
  const unread = sellerNotifications.filter((item) => !sellerReadNotificationIds.has(item.id));
  document.querySelectorAll(".seller-notif-badge").forEach((badge) => {
    badge.textContent = String(unread.length);
    badge.style.display = unread.length ? "flex" : "none";
  });
  if (!sellerNotifications.length) {
    const empty = document.createElement("p");
    empty.className = "text-sm text-gray-500 py-6 text-center";
    empty.textContent = "Hiện chưa có thông báo nào.";
    list.appendChild(empty);
    return;
  }
  sellerNotifications.forEach((notification) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px 0;border-bottom:1px solid #efd5e0";
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.className = "block text-sm";
    title.textContent = notification.title;
    const detail = document.createElement("p");
    detail.style.cssText = "font-size:13px;color:#8a727d;margin-top:4px;overflow-wrap:anywhere";
    detail.textContent = notification.content;
    content.append(title, detail);
    const action = document.createElement("button");
    action.type = "button";
    action.style.cssText = "flex:0 0 auto;color:#b95f84;font-size:12px;font-weight:700;text-decoration:underline;white-space:nowrap";
    if (!sellerReadNotificationIds.has(notification.id)) {
      action.textContent = "Đánh dấu đã đọc";
      action.addEventListener("click", () => markSellerNotificationRead(notification.id));
      row.append(content, action);
    } else {
      row.appendChild(content);
    }
    list.appendChild(row);
  });
}

function ensureSellerNotificationModal() {
  if (document.getElementById("notificationsModal")) return;
  const modal = document.createElement("div");
  modal.id = "notificationsModal";
  modal.style.cssText = "display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.4);align-items:center;justify-content:center;padding:16px";
  modal.innerHTML = `
    <div style="background:#fff;width:min(560px,100%);max-height:80vh;overflow:auto;border-radius:16px;padding:22px;box-shadow:0 12px 32px rgba(0,0,0,.18)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px">
        <h3 style="color:#b95f84">🔔 Thông báo</h3>
        <button type="button" data-close-seller-notifications aria-label="Đóng" style="font-size:24px;color:#8a727d">&times;</button>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:8px">
        <button type="button" data-refresh-seller-notifications>Cập nhật</button>
      </div>
      <div id="sellerNotificationsList"></div>
    </div>`;
  modal.addEventListener("click", (event) => {
    if (event.target === modal || event.target.closest("[data-close-seller-notifications]")) {
      modal.style.display = "none";
    }
    if (event.target.closest("[data-refresh-seller-notifications]")) {
      loadSellerNotifications().catch(handleError);
    }
  });
  document.body.appendChild(modal);
}

async function loadSellerNotifications() {
  const [orders, conversations] = await Promise.all([
    api("/seller/orders?status=pending"),
    api("/chat/conversations"),
  ]);
  const orderNotifications = orders.items.map((order) => ({
    id: `order-${order.id}`,
    title: `Đơn hàng mới #${order.id}`,
    content: `${order.buyer?.name || "Người mua"} · ${Number(order.total).toLocaleString("vi-VN")} VNĐ`,
  }));
  if (!sellerOrderNotificationBaseline) {
    orderNotifications.forEach((item) => sellerReadNotificationIds.add(item.id));
    sellerOrderNotificationBaseline = true;
    localStorage.setItem(sellerOrderBaselineKey, "true");
    persistSellerReadNotifications();
  }
  const messageNotifications = conversations.filter((item) => item.unread > 0).map((conversation) => ({
    id: `chat-${conversation.user_id}-${conversation.unread}-${conversation.last_at}`,
    userId: conversation.user_id,
    title: `Tin nhắn mới từ ${conversation.name}`,
    content: conversation.last_message,
  }));
  sellerNotifications = [...messageNotifications, ...orderNotifications];
  renderSellerNotifications();
}

async function markSellerNotificationRead(notificationId) {
  if (sellerNotificationBusy) return;
  const notification = sellerNotifications.find((item) => item.id === notificationId);
  if (!notification) return;
  sellerNotificationBusy = true;
  try {
    if (notification.userId) {
      const query = new URLSearchParams({ with: notification.userId });
      await api(`/chat/messages?${query.toString()}`);
    }
    sellerReadNotificationIds.add(notificationId);
    persistSellerReadNotifications();
    await loadSellerNotifications();
  } catch (err) {
    handleError(err);
  } finally {
    sellerNotificationBusy = false;
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest(".seller-notifications-button");
  if (!button) return;
  const modal = document.getElementById("notificationsModal");
  if (modal) modal.style.display = "flex";
  loadSellerNotifications().catch(handleError);
});

sellerOrderNotificationBaseline = localStorage.getItem(sellerOrderBaselineKey) === "true";
window.addEventListener("DOMContentLoaded", () => {
  ensureSellerNotificationModal();
  loadSellerNotifications().catch(handleError);
  window.setInterval(() => {
    if (document.visibilityState === "visible") loadSellerNotifications().catch(handleError);
  }, 60000);
});
