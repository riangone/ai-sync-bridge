// GA4 Consent Mode v2 地区默认值（待办 #30）。
// 必须在 gtag('config') 之前以同步 <script> 加载。
// 欧洲经济区（EU27 + 冰岛、列支敦士登、挪威）、英国、瑞士：四项存储默认 denied，
// 只有将来接入 Google 认证 CMP 并取得同意后，才由 CMP 发出 gtag('consent','update',…)。
// 其他地区不在这里设置，沿用页面内原有的 consent 默认值。
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('consent', 'default', {
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
  analytics_storage: 'denied',
  region: ['AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE','IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE','IS','LI','NO','GB','CH']
});
