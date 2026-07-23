var fullText = sampleContent.join(' ');

// ── Mode toggle ──
function setMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(function(b) { b.classList.remove('active'); });
  document.querySelector('.mode-btn[data-mode="' + mode + '"]').classList.add('active');
  document.getElementById('custom-settings').style.display = mode === 'custom' ? 'block' : 'none';
  document.getElementById('mode-desc').textContent = mode === 'auto'
    ? 'Use default chunk settings (recommended for most documents).'
    : 'Configure custom chunk size, overlap, and separators.';
}

// ── Slider ↔ Input sync ──
function syncInput(type) {
  var id = type === 'chunk' ? 'chunk-size-input' : 'overlap-input';
  var sliderId = type === 'chunk' ? 'chunk-size-slider' : 'overlap-slider';
  document.getElementById(id).value = document.getElementById(sliderId).value;
}
function syncSlider(type) {
  var id = type === 'chunk' ? 'chunk-size-input' : 'overlap-input';
  var sliderId = type === 'chunk' ? 'chunk-size-slider' : 'overlap-slider';
  var v = parseInt(document.getElementById(id).value) || 0;
  var min = parseInt(document.getElementById(sliderId).min);
  var max = parseInt(document.getElementById(sliderId).max);
  if (v < min) v = min;
  if (v > max) v = max;
  document.getElementById(sliderId).value = v;
}

// ── Separators ──
function addSep() {
  var input = document.getElementById('sep-input');
  var val = input.value.trim();
  if (!val) return;
  var display = val.replace(/\n/g, '\\n');
  var tags = document.getElementById('separator-tags');
  var addRow = tags.querySelector('.sep-add-row');
  var span = document.createElement('span');
  span.className = 'sep-tag';
  span.setAttribute('data-sep', val);
  span.innerHTML = display + '<button class="sep-remove" onclick="removeSep(this)">&times;</button>';
  tags.insertBefore(span, addRow);
  input.value = '';
}
function removeSep(btn) {
  btn.parentElement.remove();
}

// ── Reset ──
function resetToDefaults() {
  document.getElementById('chunk-size-slider').value = 1000;
  document.getElementById('chunk-size-input').value = 1000;
  document.getElementById('overlap-slider').value = 200;
  document.getElementById('overlap-input').value = 200;
  setMode('auto');
  document.getElementById('preview-empty').style.display = 'block';
  document.getElementById('chunk-list').style.display = 'none';
  document.getElementById('preview-pagination').style.display = 'none';
  document.getElementById('preview-summary').textContent = 'Preview to see chunk breakdown';
}

// ── Chunk Preview ──

// ── Post-Processing ──
function setParaId(val) {
  document.querySelectorAll('.para-id-btn').forEach(function(b) { b.classList.remove('selected'); });
  document.querySelector('.para-id-btn input[value="' + val + '"]').parentElement.classList.add('selected');
}

function addPostSep() {
  var input = document.getElementById('post-sep-input');
  var val = input.value.trim();
  if (!val) return;
  var display = val.replace(/\n/g, '\\n');
  var span = document.createElement('span');
  span.className = 'sep-tag';
  span.setAttribute('data-sep', val);
  span.innerHTML = display + '<button class="sep-remove" onclick="removeSep(this)">&times;</button>';
  var addRow = input.parentElement;
  addRow.insertBefore(span, input);
  input.value = '';
}

// ── Paginated Preview ──
var previewChunks = [];
var previewPage = 1;
var pageSize = 5;

function previewChunksWithPagination() {
  var mode = document.querySelector('.mode-btn.active').getAttribute('data-mode');
  var chunkSize = parseInt(document.getElementById('chunk-size-input').value) || 1000;
  var overlap = parseInt(document.getElementById('overlap-input').value) || 200;
  if (mode === 'auto') { chunkSize = 1000; overlap = 200; }

  var seps = [];
  document.querySelectorAll('.sep-tag').forEach(function(t) {
    var s = t.getAttribute('data-sep');
    seps.push(s === '\\n\\n' ? '\n\n' : s === '\\n' ? '\n' : s);
  });

  previewChunks = splitText(fullText, chunkSize, overlap, seps);
  previewPage = 1;

  document.getElementById('preview-empty').style.display = 'none';
  document.getElementById('chunk-list').style.display = 'flex';
  renderPreviewPage();
  document.getElementById('preview-pagination').style.display = 'flex';
  document.getElementById('preview-summary').textContent = previewChunks.length + ' chunks total';
}

function renderPreviewPage() {
  var list = document.getElementById('chunk-list');
  var start = (previewPage - 1) * pageSize;
  var end = Math.min(start + pageSize, previewChunks.length);
  var pageChunks = previewChunks.slice(start, end);

  list.innerHTML = pageChunks.map(function(c, i) {
    var idx = start + i + 1;
    return '<div class="chunk-card">'
      + '<div class="chunk-header"><span class="chunk-num">#' + idx + '</span><span class="chunk-chars">' + c.length + ' chars</span></div>'
      + '<div class="chunk-body">' + escapeHtml(c) + '</div></div>';
  }).join('');

  var totalPages = Math.ceil(previewChunks.length / pageSize);
  document.getElementById('page-indicator').textContent = previewPage + ' / ' + totalPages;
}

function changePage(delta) {
  var totalPages = Math.ceil(previewChunks.length / pageSize);
  var newPage = previewPage + delta;
  if (newPage < 1 || newPage > totalPages) return;
  previewPage = newPage;
  renderPreviewPage();
}

// ── Preview ──
function previewChunksOld() {
  var mode = document.querySelector('.mode-btn.active').getAttribute('data-mode');
  var chunkSize = parseInt(document.getElementById('chunk-size-input').value) || 1000;
  var overlap = parseInt(document.getElementById('overlap-input').value) || 200;
  if (mode === 'auto') { chunkSize = 1000; overlap = 200; }

  var seps = [];
  document.querySelectorAll('.sep-tag').forEach(function(t) {
    var s = t.getAttribute('data-sep');
    seps.push(s === '\\n\\n' ? '\n\n' : s === '\\n' ? '\n' : s);
  });

  var chunks = splitText(fullText, chunkSize, overlap, seps);

  document.getElementById('preview-empty').style.display = 'none';
  document.getElementById('chunk-list').style.display = 'flex';

  var list = document.getElementById('chunk-list');
  list.innerHTML = chunks.map(function(c, i) {
    return '<div class="chunk-card">'
      + '<div class="chunk-header"><span class="chunk-num">#' + (i + 1) + '</span><span class="chunk-chars">' + c.length + ' chars</span></div>'
      + '<div class="chunk-body">' + escapeHtml(c) + '</div></div>';
  }).join('');

  document.getElementById('preview-summary').textContent = chunks.length + ' chunks generated';
}

function splitText(text, maxChars, overlapChars, seps) {
  var chunks = [];
  var remaining = text;
  while (remaining.length > 0 && chunks.length < 50) {
    var end = Math.min(maxChars, remaining.length);
    var chunk = remaining.substring(0, end);
    // Try to break at a separator near the end
    for (var si = 0; si < seps.length; si++) {
      var sep = seps[si];
      if (!sep) continue;
      var idx = chunk.lastIndexOf(sep);
      if (idx > maxChars * 0.6) {
        end = idx + sep.length;
        chunk = remaining.substring(0, end);
        break;
      }
    }
    chunks.push(chunk);
    var nextStart = Math.max(0, end - overlapChars);
    remaining = remaining.substring(nextStart);
    if (nextStart === 0) break;
  }
  return chunks;
}

function escapeHtml(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Save & Re-embed ──
function saveAndReembed() {
  var mode = document.querySelector('.mode-btn.active').getAttribute('data-mode');
  var cs = document.getElementById('chunk-size-input').value;
  var ol = document.getElementById('overlap-input').value;
  if (!confirm('Save chunk config and re-embed document? (mode=' + mode + ' chunk=' + cs + ' overlap=' + ol + ')')) return;
  alert('Saved! Re-embedding will process ' + document.getElementById('doc-chunks-count').textContent + ' chunks.');
}

// ── Bootstrap from URL params ──
document.addEventListener('DOMContentLoaded', function() {
  var params = new URLSearchParams(window.location.search);
  var docId = params.get('doc');
  if (docId) {
    document.getElementById('doc-title').textContent = 'Document: ' + docId;
    document.getElementById('doc-id-label').textContent = docId;
  }
});
