// 统一的后端调用封装。
// 注: 小程序需在 mp.weixin.qq.com 后台把 BASE 的域名加入 request 合法域名。
const BASE = "https://yulai.gaokao.meno.sh";   // DNS 未生效可用 https://gaokao-yulai.onrender.com
const API_KEY = "";  // 雨来专用 key；由部署方线下交付，填入后生效

function post(path, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE + path,
      method: "POST",
      header: Object.assign(
        { "Content-Type": "application/json" },
        API_KEY ? { "Authorization": "Bearer " + API_KEY } : {}
      ),
      data: data || {},
      timeout: 90000,
      success: (res) => {
        if (res.statusCode === 401) return reject(new Error("未授权(401)：请在 utils/api.js 填入 API_KEY"));
        if (res.statusCode >= 400) return reject(new Error("HTTP " + res.statusCode));
        if (res.data && res.data.error) return reject(new Error(res.data.error));
        resolve(res.data);
      },
      fail: (e) => reject(new Error(e.errMsg || "network"))
    });
  });
}
function get(path) {
  return new Promise((resolve, reject) => {
    wx.request({ url: BASE + path, method: "GET",
      header: API_KEY ? { "Authorization": "Bearer " + API_KEY } : {},
      success: (res)=> (res.statusCode>=400? reject(new Error("HTTP "+res.statusCode)) : resolve(res.data)),
      fail: (e)=> reject(new Error(e.errMsg||"network")) });
  });
}
module.exports = {
  BASE,
  resolveOptions: (options) => post("/resolve_options", { options }),
  rankStart: (body) => post("/rank_start", body),
  rankNext: (sid, extra) => post("/rank_next", Object.assign({ sid }, extra || {})),
  rankReorder: (sid, order) => post("/rank_reorder", { sid, order }),
  rankChat: (sid, message, ctx) => post("/rank_chat", { sid, message, ctx }),
  rankEnd: (sid, body) => post("/rank_end", Object.assign({ sid }, body || {})),
  rankReport: (sid) => post("/rank_report", { sid }),
  rankRevisit: (sid) => get("/rank_revisit?key=" + sid),
  voiceIntake: (audio_b64) => post("/voice_profile?intake=1", { audio_b64 }),
  intakeChat: (payload) => post("/intake_chat", payload)
};
