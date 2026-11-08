// core/api.js: mọi lời gọi server và trạng thái đăng nhập đi qua file này.
// Nạp bằng thẻ script có src="/assets/js/core/api.js", đặt TRƯỚC script của trang.
// Không gọi fetch trực tiếp ở nơi khác (quy ước mục 6.2).

const SESSION_KEY = "fashionshop_session";
const LOGIN_PAGE = "/Sign%20in.html";

// Phiên đăng nhập lưu ở localStorage: { access_token, refresh_token, expires_at, me }
function getSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY));
  } catch (e) {
    return null;
  }
}

function saveSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

// Chặn người chưa đăng nhập hoặc sai vai trò, đưa về trang đăng nhập. Trả về hồ sơ `me` nếu hợp lệ.
function requireRole(role) {
  const session = getSession();
  if (!session || !session.me || session.me.role !== role) {
    window.location.href = LOGIN_PAGE;
    return null;
  }
  return session.me;
}

// Gọi API. Thành công trả về `data`; lỗi thì ném Error có thêm .code và .status.
async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  // FormData (tải ảnh) để trình duyệt tự đặt Content-Type kèm ranh giới; còn lại gửi JSON
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm)
    headers["Content-Type"] = "application/json";
  const session = getSession();
  if (auth && session && session.access_token) {
    headers["Authorization"] = "Bearer " + session.access_token;
  }

  let res;
  try {
    res = await fetch("/api" + path, {
      method,
      headers,
      body:
        body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch (e) {
    throw Object.assign(new Error("Không kết nối được máy chủ."), {
      code: "NETWORK",
      status: 0,
    });
  }

  let json = null;
  try {
    json = await res.json();
  } catch (e) {
    json = null;
  }

  if (!json || json.ok !== true) {
    const error = (json && json.error) || {
      code: "UNKNOWN",
      message: "Có lỗi xảy ra, vui lòng thử lại.",
    };
    // Token hết hạn: xóa phiên, lần tải trang sau sẽ được đưa về trang đăng nhập
    if (res.status === 401 && auth) clearSession();
    throw Object.assign(new Error(error.message), {
      code: error.code,
      status: res.status,
    });
  }
  return json.data;
}

// Escape dữ liệu người dùng trước khi chèn vào HTML (chống XSS, mục 6.2)
function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
