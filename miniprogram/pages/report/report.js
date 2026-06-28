Page({
  data: { blocks:[], raw:"" },
  onLoad(){
    const raw = getApp().globalData.report || "(报告为空)";
    this.setData({ raw, blocks: this.parse(raw) });
  },
  parse(md){
    const out=[];
    (md||"").split(/\n/).forEach(line=>{
      const s=line.trim();
      if(!s) return;
      if(/^#{1,6}\s/.test(s)) out.push({t:"h", x:s.replace(/^#{1,6}\s/,"")});
      else if(/^[-*]\s/.test(s)) out.push({t:"li", x:s.replace(/^[-*]\s/,"")});
      else out.push({t:"p", x:s.replace(/\*\*/g,"")});
    });
    return out;
  },
  openYusoong() {
    wx.setClipboardData({ data: "https://gaokao.yusoong.com/", success: () => wx.showToast({ title: "链接已复制,去浏览器打开", icon: "none" }) });
  },
  copy(){ wx.setClipboardData({ data: this.data.raw }); },
  restart(){ wx.reLaunch({ url:"/pages/intake/intake" }); }
});