/**
 * Audio Slide Player — image left, text right (fixed)
 * - Prefers JSON "mp3"; falls back to /audio/<Id>.(mp3|m4a|wav|mp4)
 * - ≤4 bullets; **bold** and *italic* markdown
 * - Always-fit right column by scaling inner wrapper
 * - Simple, consistent text appear animation every slide
 * - Footer shows "Quelle" and a browser-zoom hint (instruction only)
 */

document.addEventListener('DOMContentLoaded', () => {
  // ---------- DOM ----------
  let audioPlayer           = document.getElementById('audio-player');
  const slideDisplay        = document.getElementById('slide-display');
  const slideImageContainer = document.getElementById('slide-image-container');
  const slideTextContainer  = document.getElementById('slide-text-container');
  const slideTextContent    = document.getElementById('slide-text-content') || slideTextContainer; // fallback
  const sourceLinkWrap      = document.getElementById('source-link-wrap');
  const zoomHintEl          = document.getElementById('zoom-hint');

  // ---------- STATE ----------
  let slidesData = [];
  let currentSlideIndex = -1;
  let hideControlsTimeout;
  let textAnimationTimeout;

  // ---------- UTILS ----------
  const getIdFromUrl = () => new URLSearchParams(location.search).get('Id') || 'test2';

  function parseTimestamp(ts) {
    const parts = String(ts).replace(':', '_').split('_');
    const minutes = parseInt(parts[0], 10) || 0;
    const seconds = parseInt(parts[1], 10) || 0;
    return (minutes * 60) + seconds;
  }

  const escapeHTML = (s) => String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Markdown (**bold**, *italic*) → HTML with classes (colors in CSS)
  function formatMarkdownText(text) {
    let t = escapeHTML(text ?? '');
    t = t.replace(/\n/g, '<br>'); // Add this line to convert newlines to line breaks
    t = t.replace(/\*\*(.+?)\*\*/g, '<strong class="bold-text">$1</strong>'); // **bold**
    t = t.replace(/(^|[\s(])\*(.+?)\*(?=[\s).,!?:;]|$)/g, '$1<em class="italic-text">$2</em>'); // *italic*
    return t;
  }

  // ---------- RENDER ----------
  function renderSlide(slideIndex) {
    if (slideIndex === -1) {
      slideImageContainer.innerHTML = '';
      slideTextContent.innerHTML = '<p style="align-self:center; text-align:center;">Presentation loading...</p>';
      fitTextBlock();
      return;
    }

    const slide = slidesData[slideIndex];
    const id = getIdFromUrl();
    const imagePath = `images/${id}/${slide.index + 1}.png`;

    slideImageContainer.innerHTML =
      `<img src="${imagePath}" alt="${escapeHTML(slide.concept)}"
            onerror="this.style.display='none'; this.parentElement.innerHTML='<p>Image not found.</p>';">`;

    // slide_content: first line is title; show max 4 bullets below callout
    const allLines    = String(slide.slide_content || '').split('\n');
    const bulletLines = allLines.slice(1).slice(0, 4);

    const bulletsHtml = bulletLines
      .map(line => `<p class="list-item">${formatMarkdownText(line)}</p>`)
      .join('');

    slideTextContent.innerHTML = `
      <p class="explanation-callout">${formatMarkdownText(slide.explanation)}</p>
      ${bulletsHtml}
    `;

    // Ensure fixed layout: image left, text right
    slideDisplay.classList.remove('reverse');

    // Fit after layout paint
    requestAnimationFrame(fitTextBlock);
  }

  function startTextAnimation() {
    clearTimeout(textAnimationTimeout);
    const explanationElement = slideTextContent.querySelector('.explanation-callout');
    const bulletElements = slideTextContent.querySelectorAll('.list-item');
    if (!explanationElement) return;

    // Same appear animation on every slide
    textAnimationTimeout = setTimeout(() => {
      explanationElement.classList.add('visible');
      if (bulletElements.length > 0) {
        textAnimationTimeout = setTimeout(() => {
          animateBullet(0, bulletElements);
        }, 3500);
      }
    }, 200);
  }

  function animateBullet(index, elements) {
    if (index >= elements.length) return;
    elements[index].classList.add('visible');
    textAnimationTimeout = setTimeout(() => animateBullet(index + 1, elements), 900);
  }

  // ---------- FIT TEXT ----------
  function fitTextBlock() {
    if (!slideTextContainer || !slideTextContent) return;

    slideTextContent.style.transform = 'scale(1)';
    slideTextContent.style.width = 'auto';

    const containerW = slideTextContainer.clientWidth;
    const containerH = slideTextContainer.clientHeight;
    const contentW   = slideTextContent.scrollWidth;
    const contentH   = slideTextContent.scrollHeight;

    if (containerW <= 0 || containerH <= 0 || contentW <= 0 || contentH <= 0) return;

    const scaleW = containerW / contentW;
    const scaleH = containerH / contentH;
    let scale = Math.min(scaleW, scaleH, 1);
    if (scale < 0.5) scale = 0.5; // safety floor

    slideTextContent.style.transform = `scale(${scale})`;
    slideTextContent.style.width = `${(1 / scale) * 100}%`;
  }

  // Refit on size changes
  const resizeObserver = new ResizeObserver(() => requestAnimationFrame(fitTextBlock));
  resizeObserver.observe(slideDisplay);
  resizeObserver.observe(slideTextContainer);

  // ---------- AUDIO ----------
  function attachBasicAudioListeners(aEl) {
    aEl.addEventListener('timeupdate', () => updateSlide(aEl.currentTime));
    aEl.addEventListener('seeking',   () => updateSlide(aEl.currentTime));
    aEl.addEventListener('play',  resetHideControlsTimer);
    aEl.addEventListener('pause', () => {
      clearTimeout(hideControlsTimeout);
      showControls();
    });
  }

  function replaceAudioElementWithClone() {
    const clone = audioPlayer.cloneNode(true);
    audioPlayer.parentNode.replaceChild(clone, audioPlayer);
    audioPlayer = document.getElementById('audio-player');
    attachBasicAudioListeners(audioPlayer);
  }

  function tryLocalFallback(baseName) {
    const a = audioPlayer;
    const exts = ['.mp3', '.m4a', '.wav', '.mp4'];
    let i = 0;

    const tryNext = () => {
      i++;
      if (i < exts.length) {
      a.src = `../audio/${baseName}${exts[i]}`;        a.load();
      } else {
        console.error(`No local audio found for '${baseName}'.`);
        slideTextContent.innerHTML =
          `<p style="color:red;">Audio konnte nicht geladen werden (weder Remote noch lokal).</p>`;
      }
      requestAnimationFrame(fitTextBlock);
    };

    a.addEventListener('error', tryNext);
    a.addEventListener('canplay', () => a.removeEventListener('error', tryNext), { once: true });

    a.src = `audio/${baseName}${exts[i]}`;
    a.load();
  }

  function setAudioSourceFromConfigOrLocal(mp3Url, id) {
    replaceAudioElementWithClone();
    const a = audioPlayer;

    if (mp3Url && typeof mp3Url === 'string' && mp3Url.trim() !== '') {
      const onError = () => {
        const err = a.error;
        console.warn('Remote audio error', {
          code: err ? err.code : null,
          networkState: a.networkState,
          src: a.currentSrc
        });
        a.removeEventListener('error', onError);
        tryLocalFallback(id);
      };
      a.addEventListener('error', onError, { once: true });
      a.src = mp3Url.trim();
      a.load();
    } else {
      tryLocalFallback(id);
    }
  }

  // ---------- SLIDES ----------
  function updateSlide(currentTime) {
    let slideToShowIndex = -1;
    for (let i = 0; i < slidesData.length; i++) {
      if (currentTime >= slidesData[i].timestamp) slideToShowIndex = i;
      else break;
    }

    if (slideToShowIndex !== currentSlideIndex) {
      const isInitialLoad = currentSlideIndex === -1;
      clearTimeout(textAnimationTimeout);

      const updateAndShow = () => {
        currentSlideIndex = slideToShowIndex;
        renderSlide(currentSlideIndex);
        setTimeout(() => {
          startTextAnimation();
          requestAnimationFrame(fitTextBlock);
        }, isInitialLoad ? 50 : 400);
      };

      // small delay for cleanliness between switches
      setTimeout(updateAndShow, isInitialLoad ? 30 : 150);
    }
  }

  // ---------- FOOTER ZOOM HINT ----------
  function setZoomHintText() {
    if (!zoomHintEl) return;
    const isApple = /Mac|iPhone|iPad|iPod/.test(navigator.platform) || /Mac OS X/.test(navigator.userAgent);
    const minus  = isApple ? '⌘−' : 'Ctrl−';
    const reset  = isApple ? '⌘0' : 'Ctrl+0';
    zoomHintEl.textContent = `Tipp: Browser-Zoom verkleinern (${minus}). Zurücksetzen: ${reset}.`;
  }

  // ---------- AUDIO UI VISIBILITY ----------
  function showControls() { audioPlayer.classList.remove('hidden'); }
  function hideControls() { audioPlayer.classList.add('hidden'); }
  function resetHideControlsTimer() {
    clearTimeout(hideControlsTimeout);
    showControls();
    hideControlsTimeout = setTimeout(hideControls, 2500);
  }

  document.getElementById('slide-display').addEventListener('mousemove', resetHideControlsTimer);
  document.getElementById('slide-display').addEventListener('mouseleave', () => {
    hideControlsTimeout = setTimeout(hideControls, 400);
  });

  // ---------- INIT ----------
  (async function initializePlayer() {
    setZoomHintText();

    const id = getIdFromUrl();
    const slidesFile = `${id}.json`;

    try {
      const response = await fetch(`json/${slidesFile}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const rawData = await response.json();
      const { source, entries, mp3 } = rawData;

      if (sourceLinkWrap) {
        if (source) {
          sourceLinkWrap.innerHTML = `👉 <a href="${source}" target="_blank" rel="noopener noreferrer">Link</a>`;
        } else {
          sourceLinkWrap.textContent = '–';
        }
      }

      setAudioSourceFromConfigOrLocal(mp3, id);

      slidesData = (entries || [])
        .map((item, index) => ({
          index,
          timestamp: parseTimestamp(item.timestamp),
          concept: item.concept,
          explanation: item.explanation,
          slide_content: item.slide_content
        }))
        .sort((a, b) => a.timestamp - b.timestamp);

      updateSlide(audioPlayer.currentTime);
    } catch (error) {
      console.error("Error loading presentation data:", error);
      slideTextContent.innerHTML =
        `<p style="color:red;">Fehler: Konnte die Slides nicht laden (${escapeHTML(slidesFile)}).</p>`;
      if (sourceLinkWrap) sourceLinkWrap.textContent = '–';
      setAudioSourceFromConfigOrLocal(null, getIdFromUrl());
      requestAnimationFrame(fitTextBlock);
    }

    attachBasicAudioListeners(audioPlayer);
    resetHideControlsTimer();
    requestAnimationFrame(fitTextBlock);
  })();
});
