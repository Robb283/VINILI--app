// Local OCR: the image is decoded and read in this browser, never POSTed.
const photoInput = document.getElementById('photo');
const photoStatus = document.getElementById('photo-status');
let photoUrl, photoWorker, enginePromise, photoBusy = false;

function loadPhotoEngine() {
  if (!enginePromise) enginePromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/tesseract.min.js';
    script.crossOrigin = 'anonymous';
    script.integrity = 'sha384-2BQ3U3OdKOb0Uczxqr41I9UvZkzr4V9Hv8uSzMMZAlmhsFClvdZX5wi5fDCzG+tM';
    script.onload = () => resolve(window.Tesseract);
    script.onerror = () => { enginePromise = null; script.remove(); reject(new Error('Non riesco a scaricare il lettore foto. Controlla la connessione oppure scrivi il nome del disco.')); };
    document.head.append(script);
  });
  return enginePromise;
}

async function readPhoto(file) {
  if (photoBusy || !file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    photoStatus.textContent = 'Scegli una foto JPG, PNG o WebP. Per HEIC usa una copia JPG.';
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    photoStatus.textContent = 'Foto troppo grande: scegli un’immagine entro 15 MB.';
    return;
  }
  photoBusy = true;
  photoInput.disabled = true;
  document.getElementById('camera').disabled = true;
  document.getElementById('search').disabled = true;
  document.getElementById('editions').hidden = true;
  document.getElementById('assessment').hidden = true;
  document.getElementById('query').value = '';
  document.getElementById('ocr-choices').replaceChildren();
  document.getElementById('status').textContent = '';
  photoStatus.textContent = 'Preparo la lettura sul tuo dispositivo… Al primo uso scarico il motore OCR.';
  try {
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = URL.createObjectURL(file);
    const image = new Image();
    image.src = photoUrl;
    await image.decode();
    const preview = document.getElementById('photo-preview');
    preview.src = photoUrl;
    preview.hidden = false;
    // Bound OCR memory consumption and preserve enough text detail.
    const scale = Math.min(1, 2000 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    const engine = await loadPhotoEngine();
    photoWorker = await engine.createWorker('eng', 1, {
      workerPath: 'https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/worker.min.js',
      corePath: 'https://cdn.jsdelivr.net/npm/tesseract.js-core@7.0.0',
      langPath: 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int',
      logger: info => {
        if (info.status === 'recognizing text') photoStatus.textContent = `Leggo le scritte nella foto… ${Math.round(info.progress * 100)}%`;
        else if (info.status === 'loading language traineddata') photoStatus.textContent = `Scarico il modello di lettura… ${Math.round(info.progress * 100)}%`;
        else if (info.status === 'loading tesseract core') photoStatus.textContent = 'Carico il motore di lettura sul dispositivo…';
      },
    });
    const {data} = await photoWorker.recognize(canvas, {rotateAuto: true});
    const lines = data.text.split(/\r?\n/).map(s => s.trim().replace(/[|~]+$/g, '').trim().slice(0, 100)).filter(s => /[a-zA-ZÀ-ÿ]{2}/.test(s));
    if (!lines.length || data.confidence < 25) {
      photoStatus.textContent = 'Non leggo abbastanza testo per cercare. Prova una foto più vicina del titolo o dell’etichetta, oppure scrivi il nome del disco.';
      return;
    }
    // Skip obvious page controls / format metadata only in the proposed query.
    // Every detected line stays selectable: this is a heuristic, not identification.
    const metadata = /\b(?:\d+\s*[x×]?\s*LP|Repress|Reissue|Records\s*[-–—]|for sale|Collected|Wanted|Ratings|Last Sold|Lowest|Median|Highest|Discogs ID|TEST DOCUMENT)\b/i;
    const proposed = lines.filter(line => !metadata.test(line)).slice(0, 2);
    document.getElementById('query').value = proposed.join(' ').slice(0, 220);
    for (const [index, line] of lines.slice(0, 12).entries()) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ocr-chip';
      chip.textContent = line.slice(0, 100);
      chip.setAttribute('aria-pressed', proposed.includes(line) ? 'true' : 'false');
      chip.onclick = () => {
        chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
        document.getElementById('query').value = Array.from(document.querySelectorAll('.ocr-chip[aria-pressed="true"]')).map(n => n.textContent).join(' ').slice(0, 220);
        document.getElementById('query').dispatchEvent(new Event('input', {bubbles: true}));
      };
      document.getElementById('ocr-choices').append(chip);
    }
    document.getElementById('query').dispatchEvent(new Event('input', {bubbles: true}));
    photoStatus.textContent = 'Testo letto, album non ancora confermato. Controlla il campo qui sotto: puoi scegliere le righe con artista e titolo. Poi cerca le edizioni.';
  } catch (error) {
    photoStatus.textContent = error.message || 'Lettura non riuscita. Prova un’altra foto oppure scrivi il nome del disco.';
  } finally {
    if (photoWorker) { await photoWorker.terminate().catch(() => {}); photoWorker = null; }
    photoBusy = false;
    photoInput.disabled = false;
    document.getElementById('camera').disabled = false;
    document.getElementById('search').disabled = false;
  }
}

photoInput.addEventListener('change', () => { readPhoto(photoInput.files[0]); photoInput.value = ''; });
const camera = document.getElementById('camera');
camera.addEventListener('change', () => { readPhoto(camera.files[0]); camera.value = ''; });
