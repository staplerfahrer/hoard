let BUSY_LOAD_DELAY = boot.config.thumbsBusyTimeout
let RETRY_MS = boot.config.thumbsRetriesPerSec
let THUMBS_FPS = boot.config.thumbsPerSec

const thumbs = (function(){
	const ports = boot.config.thumbnailPorts
	const THUMB_NOT_LOADED = 0
	const THUMB_REQUESTED = 1
	const THUMB_ERROR = 2
	const THUMB_LOADED = 3

	let viewerState = {}

	function addViewerState(vs) {
		viewerState = vs
	}

	function setThumbnailStyle() {
		const thumbnailWidthHeight = boot.config.thumbnailWidthHeight
		const sheetContents = document.createTextNode(`
			.tn {
				width  : ${thumbnailWidthHeight[0]}px;
				height : ${thumbnailWidthHeight[1]}px;
			}

			#siblings, #children {
				width  : ${thumbnailWidthHeight[0]}px;
				height : ${thumbnailWidthHeight[1]}px;
			}

			#thumbnailContainer {
				grid-template-columns: repeat(auto-fill, ${thumbnailWidthHeight[0]}px);
			}

			.tn-wrap {
				width  : ${thumbnailWidthHeight[0]}px;
				height : ${thumbnailWidthHeight[1]}px;
			}
		`)
		const sheet = document.createElement('style')
		sheet.appendChild(sheetContents)
		document.body.appendChild(sheet)
	}

	function add(url, i) {
		// with no configured thumbnail ports, reuse the page's own port (location.port
		// is '' on the default port 80/443); window.location.hostname omits the port
		const port = ports.length ? `:${ports[i % ports.length]}` : (location.port ? `:${location.port}` : '')
		const img = document.createElement('img')
		img.classList.add('tn')
		img.classList.add('tn-loading')
		img.alt = decodeURIComponent(url)
		img.title = decodeURIComponent(url)
		img.setAttribute('data-index', i)
		img._state = THUMB_NOT_LOADED
		img._src = `${location.protocol}//${window.location.hostname}${port}${url}?tn`
		img.src = '/thumbnail-placeholder.png'
		img.onclick = toggleZoom
		// always wrap: the .tn-wrap is the grid cell and the positioning context for
		// the favorite heart (::after) and, in the recursive view, the folder caption
		const wrap = document.createElement('div')
		wrap.classList.add('tn-wrap')
		wrap.appendChild(img)
		if (viewerState.recursive) {
			// caption the file's subfolder (relative to the current dir)
			const rel = relativeFolder(url)
			if (rel) {
				const caption = document.createElement('div')
				caption.classList.add('tn-caption')
				caption.innerText = rel
				caption.title = rel
				wrap.appendChild(caption)
			}
		}
		document.getElementById('thumbnailContainer').appendChild(wrap)
		viewerState.imgElms.push(img)
	}

	function relativeFolder(url) {
		// subfolder of url relative to the current directory, sans filename ('' if directly inside)
		const base = decodeURIComponent(window.location.pathname).replace(/\/+$/, '')
		const p = decodeURIComponent(url)
		const slash = p.lastIndexOf('/')
		let dir = slash >= 0 ? p.slice(0, slash) : ''
		if (dir.startsWith(base)) dir = dir.slice(base.length)
		return dir.replace(/^\/+/, '')
	}

	function load(i) {
		const img = viewerState.imgElms[i]
		if (img._state == THUMB_REQUESTED || img._state == THUMB_LOADED)
			return
		try {
			// in case previous load didn't work, remove src
			if (img.src) img.removeAttribute('src')
			img.src = img._src
			img._state = THUMB_REQUESTED
			img.onload = (e) => {
				img.classList.remove('tn-loading')
				img._state = THUMB_LOADED
			}
			img.onerror = (e) => {
				img.classList.remove('tn-loading')
				img._state = THUMB_ERROR
			}
		} catch (e) {
			img.classList.remove('tn-loading')
			img._state = THUMB_ERROR
		}
	}

	function loadVisibleThumbs() {
		for (var i = viewerState.lowestPending; i < viewerState.imgElms.length; i++) {
			var img = viewerState.imgElms[i]
			if (!isVisible(img))
				continue
			load(i)
		}

		// An optimization.
		// From top down, while requested: these thumbs are no longer pending.
		while (viewerState.lowestPending < viewerState.imgElms.length
				&& viewerState.imgElms[viewerState.lowestPending]._requested)
			viewerState.lowestPending++

		// schedule next
		window.setTimeout(loadVisibleThumbs, 1000 / THUMBS_FPS)
	}

	function loadThumbsRandomly() {
		if (window.busyScrolling)
			// schedule next (same frame interval as below — fps is frames/sec)
			return window.setTimeout(loadThumbsRandomly, 1000 / BUSY_LOAD_DELAY)

		let next = viewerState.lowestPending + Math.floor(
			(Math.random() ** 1.6) * (viewerState.imgElms.length - viewerState.lowestPending + 1))

		while (next < viewerState.imgElms.length && viewerState.imgElms[next]._requested)
			next++

		if (next == viewerState.imgElms.length && !viewerState.imgElms.some(x => !x._requested))
			return

		if (next < viewerState.imgElms.length)
			load(next)

		// schedule next
		window.setTimeout(loadThumbsRandomly, 1000 / THUMBS_FPS)
	}

	// Re-request thumbnails that failed to load (e.g. a transient 503 while the server
	// was busy). Runs once a minute; retries the on-screen failures (off-screen ones
	// are retried when they next become visible).
	function retryFailedThumbs() {
		for (let i = 0; i < viewerState.imgElms.length; i++) {
			const img = viewerState.imgElms[i]
			if (img._state == THUMB_LOADED || img._state == THUMB_REQUESTED || !isVisible(img)) continue
			load(i)
		}
		window.setTimeout(retryFailedThumbs, RETRY_MS)
	}

	return {
		addViewerState: addViewerState,
		setThumbnailStyle: setThumbnailStyle,
		add: add,
		loadVisible: loadVisibleThumbs,
		loadRandomly: loadThumbsRandomly,
		retryFailed: retryFailedThumbs,
	}
})()
