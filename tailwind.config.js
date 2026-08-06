/** 客迹 Keji — Tailwind 配置。
 *
 * content 扫描范围：
 *  - templates/ 下全部 html（服务端渲染模板，Django Templates + HTMX 片段）
 *  - static/js/ 下全部 js（前端脚本，Alpine/HTMX 内联类名）
 *
 * 注意：注释里不要写 glob 的连续星号（会被当作块注释结束符）。
 *
 * 配色为克制的专业保险业配色：靛蓝主色 + 琥珀强调色，中性色走冷灰。
 * 所有新颜色 / 字号 / 圆角应优先复用本文件 token，避免散落魔法值。
 */

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  // 组件库类名固定保留：Tailwind 3.4 对 components 层同样 tree-shake，
  // 未在模板中即时使用的组件类会从产物消失，这里显式 safelist 保证完整输出。
  safelist: [
    "btn",
    "btn-primary",
    "btn-secondary",
    "btn-danger",
    "card",
    "badge",
    "badge-brand",
    "badge-accent",
    "badge-neutral",
    "badge-success",
    "input",
    "label",
  ],
  theme: {
    extend: {
      colors: {
        // 品牌主色：靛蓝系（专业、可信，适合金融 / 保险行业）
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          950: "#1e1b4b",
        },
        // 强调色：琥珀系（用于关键操作 / 提醒，克制使用）
        accent: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
        },
      },
      fontSize: {
        // 中文阅读排版：正文 15px，较 14px 更耐读
        body: ["0.9375rem", "1.625"],
        "body-sm": ["0.8125rem", "1.5"],
      },
      spacing: {
        // 安全触控尺寸（移动端主战场）：最小可点按目标 44px
        "touch-min": "2.75rem", // 44px
        "touch-sm": "2.5rem", // 40px（密集列表场景的次选）
      },
      borderRadius: {
        card: "0.75rem",
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(30 27 75 / 0.08), 0 1px 2px -1px rgb(30 27 75 / 0.08)",
      },
    },
  },
  plugins: [],
};
