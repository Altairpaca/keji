/* 客户关系图浏览器（T12.2 / ADR-010）。
 * 桌面交互图：vis-network 分层布局，单击节点展开其一层关系（depth=1，有限层级），
 * 右侧摘要卡显示选中客户；双击进入客户档案。
 * 手机端由模板以单层列表替代画布，本脚本不初始化（matchMedia 守卫）。
 * 依赖：static/vendor/vis-network.min.js（本地化）、Alpine、模板注入 #graph-data JSON。
 */
(function () {
  'use strict';

  // 状态语义色：与 _status_badge.html 的 15 个默认状态映射保持一致
  var STATUS_COLORS = {
    '待首次联系': '#94a3b8', '暂时无需求': '#94a3b8', '已结案': '#94a3b8',
    '电话未接': '#f59e0b', '等待回复': '#f59e0b', '多次失约': '#f59e0b',
    '已加微信': '#6366f1', '已预约': '#6366f1', '已联系': '#6366f1',
    '已见面': '#10b981', '长期维护': '#10b981', '保单服务中': '#10b981', '理赔处理中': '#10b981',
    '明确拒绝': '#ef4444', '暂停联系': '#ef4444',
  };
  var STATUS_FALLBACK = '#94a3b8';

  var DESKTOP_QUERY = '(min-width: 1024px)'; // 与模板 lg 断点一致
  var ID_PLACEHOLDER = '00000000-0000-0000-0000-000000000000'; // 模板 url 标签生成的占位 UUID

  function esc(value) {
    var s = String(value == null ? '' : value);
    return s.replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function statusColor(node) {
    return STATUS_COLORS[node.status] || STATUS_FALLBACK;
  }

  function relationLabelOf(node, edges, centerId) {
    if (node.is_center) return '中心客户';
    var found = '';
    edges.some(function (edge) {
      if (edge.from === node.id && edge.to === centerId) { found = edge.label; return true; }
      if (edge.to === node.id && edge.from === centerId) { found = edge.label; return true; }
      return false;
    });
    return found;
  }

  window.graphBrowser = function () {
    return {
      selected: null,
      loading: false,
      network: null,
      nodeDS: null,
      edgeDS: null,
      nodes: [],
      edges: [],
      centerId: null,

      init: function () {
        var container = document.getElementById('graph-canvas');
        if (!container || !window.vis) return;
        if (!window.matchMedia(DESKTOP_QUERY).matches) return; // 手机端不渲染画布

        var raw = document.getElementById('graph-data');
        if (!raw) return;
        var data = JSON.parse(raw.textContent);
        this.nodes = data.nodes || [];
        this.edges = data.edges || [];
        var center = this.nodes.filter(function (n) { return n.is_center; })[0];
        this.centerId = center ? center.id : null;

        this.nodeDS = new window.vis.DataSet();
        this.edgeDS = new window.vis.DataSet();
        this.network = new window.vis.Network(container, { nodes: this.nodeDS, edges: this.edgeDS }, this.options());
        this.network.on('click', this.onClick.bind(this));
        this.network.on('doubleClick', this.onDoubleClick.bind(this));
        this.renderData();
        this.network.fit();
      },

      options: function () {
        return {
          autoResize: true,
          layout: {
            hierarchical: {
              enabled: true,
              direction: 'LR',
              sortMethod: 'directed',
              levelSeparation: 170,
              nodeSpacing: 130,
              treeSpacing: 90,
            },
          },
          physics: false,
          nodes: {
            shape: 'dot',
            size: 18,
            borderWidth: 2,
            font: {
              face: 'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
              size: 14,
              color: '#1e293b',
              vadjust: 8,
            },
          },
          edges: {
            width: 1.5,
            color: { color: '#cbd5e1', highlight: '#6366f1', hover: '#6366f1' },
            font: { size: 12, color: '#64748b', strokeWidth: 0 },
            smooth: { enabled: true, type: 'continuous', roundness: 0.5 },
          },
          interaction: { hover: true, tooltipDelay: 150 },
        };
      },

      renderData: function () {
        var self = this;
        this.nodeDS.clear();
        this.nodeDS.add(this.nodes.map(function (n) {
          var center = n.is_center;
          return {
            id: n.id,
            label: n.label,
            level: n.depth,
            shape: center ? 'diamond' : 'dot',
            size: center ? 28 : 18,
            color: center
              ? { background: '#6366f1', border: '#4338ca', highlight: { background: '#4f46e5', border: '#4338ca' } }
              : { background: statusColor(n), border: '#334155', highlight: { background: '#818cf8', border: '#334155' } },
            title: n.status ? n.label + '（' + n.status + '）' : n.label,
          };
        }));
        this.edgeDS.clear();
        this.edgeDS.add(this.edges.map(function (e) {
          return {
            from: e.from,
            to: e.to,
            label: e.label,
            color: { color: e.color || '#cbd5e1', highlight: '#6366f1' },
            arrows: e.relation_type === 'referrer' ? { to: { enabled: true, scaleFactor: 0.6 } } : {},
          };
        }));
      },

      onClick: function (params) {
        if (!params.nodes || params.nodes.length === 0) return;
        var node = this.nodeById(params.nodes[0]);
        if (!node) return;
        this.select(node);
        if (!this.loading) this.expand(node);
      },

      onDoubleClick: function (params) {
        if (!params.nodes || params.nodes.length === 0) return;
        var node = this.nodeById(params.nodes[0]);
        if (!node) return;
        window.location.href = this.detailUrl(node.id);
      },

      nodeById: function (id) {
        var found = null;
        this.nodes.some(function (n) {
          if (n.id === id) { found = n; return true; }
          return false;
        });
        return found;
      },

      select: function (node) {
        this.selected = node;
        var label = relationLabelOf(node, this.edges, this.centerId);
        var phone = node.phone ? esc(node.phone) : '—';
        var status = node.status ? '<span class="badge-neutral">' + esc(node.status) + '</span>' : '<span class="badge-neutral">未设状态</span>';
        document.getElementById('graph-summary').innerHTML =
          '<dl class="space-y-2">' +
          '<div class="flex items-start justify-between gap-2"><dt class="text-slate-500">姓名</dt>' +
          '<dd class="text-right font-medium text-slate-900">' + esc(node.label) + '</dd></div>' +
          '<div class="flex items-start justify-between gap-2"><dt class="text-slate-500">手机</dt>' +
          '<dd class="text-right text-slate-900">' + phone + '</dd></div>' +
          '<div class="flex items-start justify-between gap-2"><dt class="text-slate-500">关系</dt>' +
          '<dd class="text-right text-slate-900">' + esc(label) + '</dd></div>' +
          '<div class="flex items-start justify-between gap-2"><dt class="text-slate-500">状态</dt><dd>' + status + '</dd></div>' +
          '</dl>' +
          '<a href="' + this.detailUrl(node.id) + '" class="btn-primary btn-sm mt-3 w-full">查看档案</a>';
      },

      // 有限层级展开：每次只拉取被点击节点的一层邻居（depth=1），合并去重后重绘
      expand: function (node) {
        var self = this;
        this.loading = true;
        var config = window.GRAPH_CONFIG || {};
        var url = (config.apiUrl || '/customers/' + node.id + '/graph/').replace(ID_PLACEHOLDER, node.id);
        fetch(url)
          .then(function (resp) { return resp.json(); })
          .then(function (data) {
            var clickedDepth = node.depth || 0;
            var known = {};
            self.nodes.forEach(function (n) { known[n.id] = n; });
            (data.nodes || []).forEach(function (n) {
              n.depth = clickedDepth + n.depth;
              if (!known[n.id]) { known[n.id] = n; self.nodes.push(n); }
            });
            var seen = {};
            self.edges.forEach(function (e) { seen[e.from + '|' + e.to] = true; });
            (data.edges || []).forEach(function (e) {
              if (!seen[e.from + '|' + e.to]) { seen[e.from + '|' + e.to] = true; self.edges.push(e); }
            });
            self.renderData();
            self.network.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
            self.loading = false;
          })
          .catch(function () { self.loading = false; });
      },

      detailUrl: function (id) {
        var config = window.GRAPH_CONFIG || {};
        return (config.detailUrl || '/customers/' + id + '/').replace(ID_PLACEHOLDER, id);
      },
    };
  };
})();
