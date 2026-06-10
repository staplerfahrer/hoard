// UI elements
let vb             = null // viewBox
let vi             = null // viewImage (active buffer)
let vi2            = null // viewImage (back buffer, preloads next)
let vi3            = null // viewImage (back buffer, preloads prev)
let vv             = null // viewVideo
let vpdf           = null // viewPdf iframe
let vclose         = null // viewPdf close button
let autoPlayButton = null

// UI state
const viewerState = {
	playState            : 'galleryMode', // galleryMode, viewMode, autoPlayMode
	videoState           : 'none', // none, playing
	autoPlay             : 0,
	viewing              : false,
	viewedIndex          : 0,
	imgUrls              : boot.data.imgUrls,
	kinds                : boot.data.kinds, // one char per imgUrl: KIND_* code
	flags                : boot.data.flags, // one char per imgUrl: FLAG_* code
	recursive            : boot.data.recursive, // show-all-subfolders view
	dirUrls              : boot.data.dirUrls,
	imgElms              : [],
	dirElms              : {},
	viewportUnzoomedScale: window.visualViewport.scale,
	pageScrollYPos       : null,
	scrolledPixelsWhileBusy: 0,
	lowestPending        : 0,
}

thumbs.addViewerState(viewerState)
thumbs.setThumbnailStyle()

let cache          = {}
let siblingUrls    = boot.data.siblingUrls
let allowDelete    = boot.config.allowDelete
let displayUnrenderables = boot.config.displayUnrenderables
let preferAltNavigation = boot.config.preferAltNavigation
// modifier for directory navigation (Ctrl by default, Alt if preferred)
const navMod = preferAltNavigation ? 'altKey' : 'ctrlKey'

// viewer file kinds — mirror filesystem.py classify() codes (packed in viewerState.kinds)
const KIND_UNVIEWABLE = '0'
const KIND_IMAGE      = '1'
const KIND_VIDEO      = '2'
const KIND_PDF        = '3'

// per-file flag states — mirror flags.py (packed in viewerState.flags); pressing
// 'p' (or the bar button) cycles a file none → pick → reject → none
const FLAG_NONE   = 'n'
const FLAG_PICK   = 'p'
const FLAG_REJECT = 'r'
const FLAG_CYCLE  = { [FLAG_NONE]: FLAG_PICK, [FLAG_PICK]: FLAG_REJECT, [FLAG_REJECT]: FLAG_NONE }
const FLAG_STATE  = { [FLAG_NONE]: 'none', [FLAG_PICK]: 'pick', [FLAG_REJECT]: 'reject' }

// Canonical comparison for two URL paths: compare their fully-DECODED forms, so a
// match is independent of which encoder (Python's quote vs the browser) produced
// the percent-escapes. Use decodeURIComponent (not decodeURI) so reserved chars
// like %26 '&' and %23 '#' decode too — the same reason labels use it.
function samePath(a, b) {
	try { return decodeURIComponent(a) === decodeURIComponent(b) }
	catch (e) { return a === b }   // malformed %xx — fall back to a raw compare
}

vb = document.getElementById('viewBox')
vi = document.getElementById('viewImg')
vi2 = document.getElementById('viewImg2')
vi2.style.display = 'none'
vi3 = document.getElementById('viewImg3')
vi3.style.display = 'none'
vv = document.getElementById('viewVideo')
vpdf = document.getElementById('viewPdf')
vclose = document.getElementById('viewPdfClose')
vclose.onmouseup = (e) => { e.stopPropagation(); toggleZoom() }
autoPlayButton = document.getElementById('autoPlayButton')

function buildDom() {
	// optionally drop files the viewer can't render (keeps imgUrls/kinds aligned)
	if (!displayUnrenderables) {
		const keptUrls = []
		let keptKinds = ''
		let keptFlags = ''
		for (let i = 0; i < viewerState.imgUrls.length; i++) {
			if (viewerState.kinds[i] === KIND_UNVIEWABLE) continue
			keptUrls.push(viewerState.imgUrls[i])
			keptKinds += viewerState.kinds[i]
			keptFlags += viewerState.flags[i]
		}
		viewerState.imgUrls = keptUrls
		viewerState.kinds = keptKinds
		viewerState.flags = keptFlags
	}

	const beautifyLabel = (l) => l.replace(/^\//, '').replaceAll('/', '▹')
	const currentPathLabel = beautifyLabel(decodeURIComponent(window.location.pathname))
	const title1 = `hoard ${viewerState.imgUrls.length} ${currentPathLabel}`
	document.title = title1

	const count = viewerState.imgUrls.length
	const title2 = `${currentPathLabel} <span style="opacity:0.5">—</span> ${count} ${count === 1 ? 'file' : 'files'}`
	document.getElementById('titleContainer').innerHTML = title2

	viewerState.imgUrls.forEach(thumbs.add)
	for (let i = 0; i < viewerState.imgElms.length; i++) applyFlag(i)

	buildDirectoryGrid(siblingUrls, viewerState.dirUrls)

	let cur = window.location.pathname            // encoded form — for hrefs & '/' checks
	let idx = siblingUrls.findIndex(u => samePath(u, cur))

	const np = document.getElementById('navPrevious')
	if (idx > 0) {
		np.onclick = ()=>{navigateTo(siblingUrls[idx - 1]); return false}
		np.href = siblingUrls[idx - 1]
		np.innerText += ' ' + beautifyLabel(decodeURIComponent(siblingUrls[idx - 1]))
	} else {
		np.classList.add('nav-hidden')
	}

	const nu = document.getElementById('navUp')
	if (cur !== '/') {
		nu.onclick = ()=>{navigateTo(viewerState.dirUrls[0]); return false}
		nu.href = viewerState.dirUrls[0]
		nu.innerText += ' ' + beautifyLabel(decodeURIComponent(viewerState.dirUrls[0]))
	} else {
		nu.classList.add('nav-hidden')
	}

	const nn = document.getElementById('navNext')
	if (idx !== -1 && idx < siblingUrls.length - 1) {
		nn.onclick = ()=>{navigateTo(siblingUrls[idx + 1]); return false}
		nn.href = siblingUrls[idx + 1]
		nn.innerText = beautifyLabel(decodeURIComponent(siblingUrls[idx + 1])) + ' ' + nn.innerText
	} else {
		nn.classList.add('nav-hidden')
	}

	// "all" toggle: switch between this folder and the recursive (?all) view
	const na = document.getElementById('navAll')
	if (cur === '/') {
		na.classList.add('nav-hidden') // recursive is meaningless at the virtual root
	} else {
		const allTarget = window.location.origin + cur + (viewerState.recursive ? '' : '?all')
		na.href = allTarget
		na.onclick = () => {
			updateCookie(allTarget, 0) // keep resume cookie in sync so it doesn't bounce back
			window.location.href = allTarget
			return false
		}
		if (viewerState.recursive) na.classList.add('active')
	}

	vv.onplay    = e => {viewerState.videoState = 'playing'}
	vv.onplaying = e => {viewerState.videoState = 'playing'}
	vv.onpause   = e => {viewerState.videoState = 'none'}
	vv.onending  = e => {viewerState.videoState = 'none'}
	vv.onwaiting = e => {viewerState.videoState = 'none'}
}

//#region MARK:cookie stuff
function resumeSession() {
	if (window.location.search.includes('override')) {
		updateCookie(window.location.origin + window.location.pathname, 0)
		return
	}
	if (!document.cookie) {
		window.setTimeout(() => {
			updateCookie(window.location.href, viewerState.viewedIndex)
		}, 10000)
		return
	}

	let location = getCookie('location=')
	if (!samePath(window.location.href, location)) {
		fetch(location).then(r => {
			if (r.ok) { window.location.href = location; return; }
			updateCookie(window.location.origin + '/', 0)
			window.location.href = '/'
		}).catch(() => {
			updateCookie(window.location.origin + '/', 0)
			window.location.href = '/'
		})
		return
	}

	let index = getCookie('viewIndex=i')
	if (viewerState.viewedIndex !== index)
		viewerState.viewedIndex = Number(index)
}

function getCookie(label) {
	let values = document.cookie.split('; ')
	for (let i = 0; i < values.length; i++) {
		if (values[i].indexOf(label) === -1) continue
		return values[i].replace(label, '')
	}
}

function updateCookie(newPath, newIndex, newLastChild) {
	function setCookie(value) {
		let cookieTime  = new Date()
		let now         = cookieTime.getTime()
		let expireTime  = now + 3660 * 86400 * 1000
		cookieTime.setTime(expireTime)
		let expiresString = cookieTime.toUTCString()
		let newCookie = (
			value
			+ '; path=/'
			+ '; expires=' + expiresString)
		document.cookie = newCookie
	}

	function clearCookies() {
		// clear old cookies, from stack overflow
		let expire = '=;expires=' + new Date().toUTCString() + ';path=/'
		document.cookie.split(';').forEach(c => {
			document.cookie = c
				.replace(/^ +/, '')
				.replace(/=.*/, expire)
		});
	}

	let lastChild = newLastChild !== undefined ? newLastChild : getCookie('lastChild=')
	clearCookies()
	setCookie('location=' + newPath)
	setCookie('viewIndex=i' + newIndex) // can't set it to just 0
	if (lastChild) setCookie('lastChild=' + lastChild)
}
//#endregion

//#region MARK:view/nav
function toggleZoom(e) {
	if (window.zoomed) { // todo: this is viewerState stuff
		// viewBox
		vb.style.visibility = 'hidden'

		// viewImage
		// so that on next view, it doesn't show the old image
		vi.src = ''
		vi.classList.remove('slowZoom')
		vi.style.display = 'none'

		// viewVideo
		vv.pauseInterval = setInterval(()=>{
			vv.pause()
			if (viewerState.videoState == 'none')
				clearInterval(vv.pauseInterval)
		}, 500)
		vv.style.display = 'none'

		// viewPdf
		vpdf.style.display = 'none'
		vpdf.src = ''
		vclose.style.display = 'none'

		delete window.zoomed
		changeAutoPlay('disable')
		return
	}

	if (viewerState.viewedIndex >= viewerState.imgUrls.length) {
		return
	}

	if (e && e.target.tagName === 'IMG') {
		// if an image was clicked, get the index
		let clickedImg = e.target
		viewerState.viewedIndex = Number(clickedImg.getAttribute('data-index'))
	}

	viewerState.imgElms.forEach(img => {
		if (img._requested && !img._loaded) {
			img.src = '/thumbnail-placeholder.png'
			img.classList.add('tn-loading')
			img._requested = false
		}
	})
	viewerState.lowestPending = 0

	window.zoomed = true
	vb.style.visibility = 'visible'
	updateViewed()
}

function changeAutoPlay(option) {
	document.getElementById('autoPlayButton').classList.remove('autoPlaying')

	if (option === 'disable') {
		if (!window.autoPlay) return; // not running
		// clear timer
		if (window.zoomed) toggleZoom()
		window.clearInterval(window.autoPlay)
		delete window.autoPlay
	}

	if (option === 'reset') {
		if (!window.autoPlay) return; // not running
		// clear & set new timer
		window.clearInterval(window.autoPlay)
		document.getElementById('autoPlayButton').classList.add('autoPlaying')
		window.autoPlay = window.setInterval(()=>{
			viewerState.viewedIndex++
			updateViewed()
		}, boot.config.autoPlayTimer)
	}

	if (option === 'toggle') {
		if (window.autoPlay) {
			// running, clear timer
			if (window.zoomed) toggleZoom()
			window.clearInterval(window.autoPlay)
			delete window.autoPlay
		} else {
			// not running, set timer
			if (!window.zoomed) toggleZoom()
			document.getElementById('autoPlayButton').classList.add('autoPlaying')
			window.autoPlay = window.setInterval(()=>{
				viewerState.viewedIndex++
				updateViewed()
			}, boot.config.autoPlayTimer)
		}
	}
}

// The element actually laid out as a grid cell for a thumbnail: the .tn-wrap in the
// recursive '?all' view, otherwise the <img> itself. Measuring the <img> directly
// breaks in recursive view — each img sits in a position:relative .tn-wrap, so its
// offsetTop is 0 relative to that wrapper instead of reflecting its grid row.
function cellOf(img) {
	const p = img.parentElement
	return p && p.classList.contains('tn-wrap') ? p : img
}

function imagesPerRow() {
	const n = viewerState.imgElms.length
	if (n === 0) return 1
	const cells = viewerState.imgElms.map(cellOf)
	// skip the first thumbnail row: it's short by two cells because #siblings and
	// #children share the grid. The second row is full, giving the true column count.
	const firstTop = cells[0].offsetTop
	let i = 0
	while (i < n && cells[i].offsetTop === firstTop) i++
	if (i >= n) return n            // only one thumbnail row
	const rowTop = cells[i].offsetTop
	let count = 0
	while (i < n && cells[i].offsetTop === rowTop) { i++; count++ }
	return count || 1
}

// number of thumbnails in one viewport-height "page" (columns × visible rows)
function thumbsPerPage() {
	const n = viewerState.imgElms.length
	if (n === 0) return 1
	const cells = viewerState.imgElms.map(cellOf)
	const perRow = imagesPerRow()
	// row stride = offsetTop gap to the next row (includes the CSS grid gap); fall
	// back to a cell's own height when everything fits on a single row
	const firstTop = cells[0].offsetTop
	let k = 0
	while (k < n && cells[k].offsetTop === firstTop) k++
	const stride = k < n ? cells[k].offsetTop - firstTop : cells[0].offsetHeight
	const rows = Math.max(1, Math.floor(window.innerHeight / stride))
	return perRow * rows
}

// nearest index (from start, inclusive) the viewer can display, scanning
// by dir (+1/-1) with wrap-around; -1 if nothing is viewable.
function nextViewableIndex(start, dir) {
	const n = viewerState.imgUrls.length
	let i = start
	for (let count = 0; count < n; count++) {
		if (i < 0) i = n - 1
		else if (i >= n) i = 0
		if (viewerState.kinds[i] !== KIND_UNVIEWABLE) return i
		i += dir
	}
	return -1
}

function updateViewed(dir = 1) {
	const n = viewerState.imgUrls.length
	if (n === 0) return
	// wrap
	if (viewerState.viewedIndex < 0) viewerState.viewedIndex = n - 1
	else if (viewerState.viewedIndex >= n) viewerState.viewedIndex = 0
	// skip files the viewer can't display, continuing in the travel direction
	const landed = nextViewableIndex(viewerState.viewedIndex, dir >= 0 ? 1 : -1)
	if (landed === -1) return // nothing displayable
	viewerState.viewedIndex = landed

	updateCookie(window.location.href, viewerState.viewedIndex)
	borderViewed()
	updateFlagButton()
	if (!window.zoomed) return

	// update & display
	let url = viewerState.imgUrls[viewerState.viewedIndex]
	const kind = viewerState.kinds[viewerState.viewedIndex]
	if (kind === KIND_PDF) {
		// pdf
		vv.style.display = 'none'
		vi.style.display = 'none'
		vpdf.src = url
		vpdf.style.display = ''
		vclose.style.display = ''
	} else if (kind === KIND_VIDEO) {
		// video
		vi.style.display = 'none'
		vi.classList.remove('slowZoom')
		vpdf.style.display = 'none'
		vclose.style.display = 'none'
		// https://stackoverflow.com/questions/5235145/changing-source-on-html5-video-tag
		vv.style.display = 'inline-block'
		let vvSources = vv.getElementsByTagName('source')
		let source = vvSources[0]
		if (!source) {
			source = document.createElement('source')
			source.setAttribute('src', url)
			source.setAttribute('type', 'video/mp4')
			vv.appendChild(source)
		} else {
			vv.pause()
			source.setAttribute('src', url)
			source.setAttribute('type', 'video/mp4')
			vv.load()
		}
		vv.play()
	} else {
		vpdf.style.display = 'none'
		vclose.style.display = 'none'
		vv.pause()
		vv.style.display = 'none'
		// picture — triple-buffered to avoid flicker in both directions
		const absUrl = new URL(url, location.href).href
		const vi2Hit = vi2.complete && vi2.naturalWidth > 0 && vi2.src === absUrl
		const vi3Hit = !vi2Hit && vi3.complete && vi3.naturalWidth > 0 && vi3.src === absUrl
		if (vi2Hit || vi3Hit) {
			// a back buffer already has this image — swap instantly
			vi.style.display = 'none'
			vi.classList.remove('slowZoom')
			vi.onload = null
			if (vi2Hit) { ;[vi, vi2] = [vi2, vi] } else { ;[vi, vi3] = [vi3, vi] }
			vi2.style.display = 'none'
			vi2.onload = null
			vi3.style.display = 'none'
			vi3.onload = null
			vi.style.display = ''
			vi.style.visibility = 'hidden'
			zoomStyle()
		} else {
			vi.style.display = ''
			vi.style.visibility = 'hidden'
			vi.onload = zoomStyle
			vi.src = url
		}
		// preload next into vi2, prev into vi3
		const nextIdx = viewerState.viewedIndex + 1
		if (nextIdx < viewerState.imgUrls.length && viewerState.kinds[nextIdx] === KIND_IMAGE) {
			const nextUrl = viewerState.imgUrls[nextIdx]
			if (vi2.src !== new URL(nextUrl, location.href).href) {
				vi2.onload = null
				vi2.src = nextUrl
			}
		}
		const prevIdx = viewerState.viewedIndex - 1
		if (prevIdx >= 0 && viewerState.kinds[prevIdx] === KIND_IMAGE) {
			const prevUrl = viewerState.imgUrls[prevIdx]
			if (vi3.src !== new URL(prevUrl, location.href).href) {
				vi3.onload = null
				vi3.src = prevUrl
			}
		}
		cacheNextImages()
	}
	window.location.hash=url
}

function zoomStyle() {
	// https://alvarotrigo.com/blog/change-css-javascript/

	function recalculateZoomRange() {
		let xScale = Math.max(window.innerWidth / vi.naturalWidth, 1) * 0.95
		let yScale = Math.max(window.innerHeight / vi.naturalHeight, 1) * 0.95
		let startScale = Math.min(xScale, yScale)
		let endScale   = Math.max(xScale, yScale) * 1.1
		let zoomSpeed  = (boot.config.zoomSpeed || 1) * endScale / startScale
		let sheet = `
			@keyframes slowZoom {
				0% { transform: scale(`+startScale+`); }
				100% { transform: scale(`+endScale+`); }
			}
			.slowZoom {
				animation: slowZoom `+zoomSpeed+`s;
				animation-fill-mode: forwards;
				animation-timing-function: ease-in-out-sine;
			}
			`
		let e2 = document.createElement('style')
		e2.appendChild(document.createTextNode(sheet))
		let e = document.getElementById('slowZoomSheet')
		e.replaceWith(e2)
		e2.id = 'slowZoomSheet'

		vi.offsetHeight; // reset zoom
		vi.classList.add('slowZoom')
		vi.style.visibility = 'visible'
	}

	vi.classList.remove('slowZoom')
	recalculateZoomRange()
}

function currentlyScrolling() {
	let scrolling = viewerState.pageScrollYPos !== document.documentElement.scrollTop
	viewerState.pageScrollYPos = document.documentElement.scrollTop
	return scrolling
}

function navigateTo(relUrl) {
	let absUrl
	if (relUrl === '..') {
		let segs = window.location.pathname.split('/').filter(Boolean)
		segs.pop()
		absUrl = window.location.origin + (segs.length ? '/' + segs.join('/') : '/')
	} else {
		absUrl = window.location.origin + relUrl
	}

	// highlight now so bfcache preserves it when hitting back
	let elm = viewerState.dirElms[relUrl]
	if (elm) elm.classList.add('selection-outline')

	// keep last 2 navigated-to dirs
	let parts = (getCookie('lastChild=') || '').split('|').filter(Boolean)
	parts.unshift(relUrl)
	updateCookie(absUrl, 0, parts.slice(0, 2).join('|'))
	window.location.href = absUrl
}

function navigate(e) {
	navigateTo(e.target.getAttribute('href'))
}
//#endregion

function highlightLastDir() {
	let lastChild = getCookie('lastChild=')
	if (!lastChild) return
	let scrollTarget = null
	lastChild.split('|').forEach(function(url) {
		let elm = viewerState.dirElms[url]
		if (!elm) return
		elm.classList.add('selection-outline')
		if (!scrollTarget) scrollTarget = elm
	})
	if (scrollTarget) scrollTarget.scrollIntoView()
}

function buildDirectoryGrid(siblings, children) {
	let makeLink = url => {
		let a       = document.createElement('a')
		a.href      = url
		a.onclick   = navigate // todo: ugh
		a.innerText = decodeURIComponent(url.split('/').at(-1) || url)
		if (samePath(url, window.location.pathname)) {
			a.classList.add('active')
		}
		// index by URL so navigateTo()/highlightLastDir() can find this element
		// (keys match: callers look up the same server-encoded url strings)
		viewerState.dirElms[url] = a
		return a
	}

	let sblns = siblings.map(makeLink)
	let chlns = children.map(makeLink)

	let sbox = document.getElementById('siblings')
	let cbox = document.getElementById('children')

	sbox.append(...sblns)
	cbox.append(...chlns)

	sbox.childNodes.forEach(c => {
		if (!c.classList.contains('active')) return
		c.parentElement.scrollTop = Math.max(
			c.offsetTop - c.parentElement.offsetTop - (c.parentElement.clientHeight / 2 - c.clientHeight),
			0)
	})
}
//#endregion

function isVisible(x) {
	let loadExtra      = 100
	// measure the grid cell, not the <img>: in recursive view the img is wrapped in
	// a position:relative .tn-wrap, so img.offsetTop is ~0 relative to that wrapper
	const cell         = cellOf(x)
	// https://stackoverflow.com/questions/4096863/how-to-get-and-set-the-current-web-page-scroll-position
	let visibleTop     = document.documentElement.scrollTop
	let visibleBottom  = document.documentElement.clientHeight + visibleTop
	let itemTop        = cell.offsetTop
	let itemBottom     = itemTop + cell.offsetHeight
	let boundaryTop    = visibleTop - loadExtra
	let boundaryBottom = visibleBottom + loadExtra
	return (itemBottom > boundaryTop && itemTop < boundaryBottom)
}

function borderViewed(scroll = true) {
	for (let i = 0; i < viewerState.imgElms.length; i++) {
		const elmtAtIdx = viewerState.imgElms[i]
		const elmtDataIdx = elmtAtIdx.getAttribute('data-index')
		elmtAtIdx.classList.remove('selection-outline')
		if (elmtDataIdx == viewerState.viewedIndex) {
			elmtAtIdx.classList.add('selection-outline')
			// scroll using the grid cell's page offset (see isVisible) so recursive
			// view (wrapped thumbnails) scrolls to the active thumbnail correctly
			if (scroll) document.documentElement.scrollTop = Math.max(cellOf(elmtAtIdx).offsetTop - 400, 0)
		}
	}
}

// long-press selection: mark a thumbnail as the current item (outline it, set the
// index for keyboard nav / flagging) WITHOUT opening the viewer. No scroll — the
// pressed thumbnail is already under the cursor.
function selectThumb(index) {
	if (index < 0 || index >= viewerState.imgUrls.length) return
	viewerState.viewedIndex = index
	borderViewed(false)
	updateFlagButton()
	updateCookie(window.location.href, viewerState.viewedIndex)
}

//#region MARK:flags
// reflect a file's flag on its thumbnail (FLAG_NONE clears it)
function applyFlag(i) {
	const el = viewerState.imgElms[i]
	if (!el) return
	el.classList.remove('flag-pick', 'flag-reject')
	const f = viewerState.flags[i]
	if (f === FLAG_PICK)   el.classList.add('flag-pick')
	else if (f === FLAG_REJECT) el.classList.add('flag-reject')
}

// paint the bar button with the currently-viewed file's flag state
function updateFlagButton() {
	const fb = document.getElementById('flagButton')
	if (!fb) return
	const f = viewerState.flags[viewerState.viewedIndex] || FLAG_NONE
	fb.classList.remove('flag-pick', 'flag-reject')
	if (f === FLAG_PICK)   fb.classList.add('flag-pick')
	else if (f === FLAG_REJECT) fb.classList.add('flag-reject')
}

// advance the viewed file's flag (none → pick → reject → none) and persist it
function cycleFlag() {
	const i = viewerState.viewedIndex
	if (i < 0 || i >= viewerState.imgUrls.length) return
	const next = FLAG_CYCLE[viewerState.flags[i] || FLAG_NONE]
	viewerState.flags = viewerState.flags.slice(0, i) + next + viewerState.flags.slice(i + 1)
	applyFlag(i)
	updateFlagButton()
	fetch(viewerState.imgUrls[i] + '?flag=' + FLAG_STATE[next]).then(r => r.text()).then(result => {
		if (result !== 'ok') console.log('flag failed:', result)
	})
}
//#endregion

function cacheNextImages() {
	window.setTimeout(() => {
		for (let i = 0; i < 10; i++) {
			let nextIndex = viewerState.viewedIndex + 1 + i
			if (nextIndex === viewerState.imgUrls.length) return

			let cacheUrl = viewerState.imgUrls[nextIndex]
			if (cacheUrl in cache) continue
			let c = document.createElement('img')
			c.src = cacheUrl
			cache[cacheUrl] = c
		}
	}, 500)
}

//#region MARK:user events
// TODO: I wonder if the keyboard just needs to focus a control, like tab...
function bindEvents() {
	// vb.onclick = toggleZoom
	vb.onmouseup = toggleZoom

	document.querySelector('#backToTop').onclick = () => {
		document.documentElement.scrollTop = 0
	}

	document.getElementById('flagButton').onclick = cycleFlag

	// press-and-hold a thumbnail to SELECT it (outline only); a quick click still
	// opens it (img.onclick = toggleZoom). Delegated on the container so it scales.
	const LONG_PRESS_MS = 400
	let pressTimer = null
	let pressStartX = 0, pressStartY = 0
	let longPressed = false
	const tc = document.getElementById('thumbnailContainer')

	tc.addEventListener('mousedown', (e) => {
		if (e.button !== 0) return                 // left button only
		const img = e.target.closest('.tn')
		if (!img) return
		longPressed = false
		pressStartX = e.clientX; pressStartY = e.clientY
		const index = Number(img.getAttribute('data-index'))
		clearTimeout(pressTimer)
		pressTimer = setTimeout(() => { longPressed = true; selectThumb(index) }, LONG_PRESS_MS)
	})
	// cancel the pending long-press on release, on leaving the grid, or once the
	// pointer moves far enough that this is a drag/scroll rather than a hold
	tc.addEventListener('mouseup',    () => clearTimeout(pressTimer))
	tc.addEventListener('mouseleave', () => clearTimeout(pressTimer))
	tc.addEventListener('mousemove',  (e) => {
		if (Math.abs(e.clientX - pressStartX) > 10 || Math.abs(e.clientY - pressStartY) > 10)
			clearTimeout(pressTimer)
	})
	// a long press is followed by a click event — swallow it (capture phase, before
	// the thumbnail's own onclick) so the hold selects instead of opening
	tc.addEventListener('click', (e) => {
		if (longPressed) { e.stopPropagation(); e.preventDefault(); longPressed = false }
	}, true)

	// prevent accidental dragging of clickable elements
	vi.ondragstart  = (e) => e.preventDefault()
	vi2.ondragstart = (e) => e.preventDefault()
	vi3.ondragstart = (e) => e.preventDefault()
	document.querySelectorAll('.tn, a').forEach((tn) => {
		tn.ondragstart = (e) => e.preventDefault()
	})

	document.onkeydown = (e) => {
		// directory navigation
		if      (e[navMod] && e.key == 'ArrowUp'   ) {
			e.preventDefault()
			const idx = siblingUrls.findIndex(u => samePath(u, window.location.pathname))
			if (idx > 0) navigateTo(siblingUrls[idx - 1])
		}
		else if (e[navMod] && e.key == 'ArrowLeft' ) {
			e.preventDefault()
			navigateTo(viewerState.dirUrls[0])
		}
		else if (e[navMod] && e.key == 'ArrowRight') {
			e.preventDefault()
			if (viewerState.dirUrls.length > 1) navigateTo(viewerState.dirUrls[1])
		}
		else if (e[navMod] && e.key == 'ArrowDown' ) {
			e.preventDefault()
			const idx = siblingUrls.findIndex(u => samePath(u, window.location.pathname))
			if (idx !== -1 && idx < siblingUrls.length - 1) navigateTo(siblingUrls[idx + 1])
		}
		// home/end
		else if (e.key == 'Home') {
			viewerState.viewedIndex = 0
			updateViewed()
		}
		else if (e.key == 'End') {
			viewerState.viewedIndex = viewerState.imgUrls.length - 1
			updateViewed()
		}
		// page up/down — jump a full screen of thumbnails
		else if (e.key == 'PageUp') {
			e.preventDefault()
			viewerState.viewedIndex = Math.max(viewerState.viewedIndex - thumbsPerPage(), 0)
			updateViewed(-1)
		}
		else if (e.key == 'PageDown') {
			e.preventDefault()
			viewerState.viewedIndex = Math.min(viewerState.viewedIndex + thumbsPerPage(), viewerState.imgUrls.length - 1)
			updateViewed(1)
		}
		// arrow keys
		else if (e.key == 'ArrowLeft' ) {
			viewerState.viewedIndex--
			changeAutoPlay('reset')
			updateViewed(-1)
		}
		else if (e.key == 'ArrowRight') {
			viewerState.viewedIndex++
			changeAutoPlay('reset')
			updateViewed(1)
		}
		else if (e.key == 'ArrowUp'   ) {
			e.preventDefault()
			viewerState.viewedIndex -= imagesPerRow()
			changeAutoPlay('reset')
			updateViewed(-1)
		}
		else if (e.key == 'ArrowDown' ) {
			e.preventDefault()
			viewerState.viewedIndex += imagesPerRow()
			changeAutoPlay('reset')
			updateViewed(1)
		}
		// toggle viewing
		else if (e.key == 'Escape' || e.key == 'Enter') {
			toggleZoom()
		}
		// toggle full screen
		else if (e.key == 'f') {
			// todo: not nice, use global state object
			// todo: esc doesn't stop the video
			const fe = document.fullscreenElement
			if (!fe) {
				vv.requestFullscreen()
			} else {
				document.exitFullscreen()
			}
		}
		// video controls
		else if (e.code == 'Space') {
			e.preventDefault()
			if (viewerState.videoState == 'none')
				vv.play()
			else
				vv.pause()
		}
		// delete
		else if (e.key == 'Delete' && allowDelete) {
			const url = viewerState.imgUrls[viewerState.viewedIndex]
			if (confirm('Mark this file for deletion?\n\n' + decodeURIComponent(url).split('/').at(-1))) {
				fetch(url + '?del').then(r => r.text()).then(result => {
					if (result !== 'ok') { alert('Delete failed: ' + result); return; }
					let idx = viewerState.viewedIndex
					viewerState.imgElms[idx].remove()
					viewerState.imgElms.splice(idx, 1)
					viewerState.imgUrls.splice(idx, 1)
					viewerState.kinds = viewerState.kinds.slice(0, idx) + viewerState.kinds.slice(idx + 1)
					viewerState.flags = viewerState.flags.slice(0, idx) + viewerState.flags.slice(idx + 1)
					if (idx < viewerState.lowestPending) viewerState.lowestPending--
					for (let i = idx; i < viewerState.imgElms.length; i++)
						viewerState.imgElms[i].setAttribute('data-index', i)
					if (viewerState.imgUrls.length === 0) { toggleZoom(); return; }
					if (viewerState.viewedIndex >= viewerState.imgUrls.length)
						viewerState.viewedIndex = viewerState.imgUrls.length - 1
					updateViewed()
				})
			}
		}
		// explorer
		else if (e.key == 'e') {
			fetch(viewerState.imgUrls[viewerState.viewedIndex] + '?explorer')
		}
		// flag: cycle none → pick → reject → none
		else if (e.key == 'p') {
			cycleFlag()
		}
	}

	//////// horizontal scrolling
	document.addEventListener('wheel', (e) => {
		// don't scroll the grid when zoomed
		if (window.zoomed) e.preventDefault()

		let scrolledPixels = window.zoomed ? e.deltaY : e.deltaX

		viewerState.scrolledPixelsWhileBusy += scrolledPixels

		if (window.busyScrolling) return

		if (viewerState.scrolledPixelsWhileBusy >= 100) {
			window.busyScrolling = true
			viewerState.viewedIndex++
			changeAutoPlay('reset')
			updateViewed(1)
		} else if (viewerState.scrolledPixelsWhileBusy <= -100) {
			window.busyScrolling = true
			viewerState.viewedIndex--
			changeAutoPlay('reset')
			updateViewed(-1)
		}

		if (window.busyScrolling) {
			viewerState.scrolledPixelsWhileBusy = 0
			window.setTimeout(() => {
				delete window.busyScrolling
			}, boot.config.scrollRateLimitMs)
		}
	}, { passive: false })

	// autoPlay
	autoPlayButton.onclick = () => {
		// if (window.innerWidth == screen.width && window.innerHeight == screen.height) {
		// 	document.exitFullscreen()
		// } else {
		// 	document.body.requestFullscreen()
		// }
		changeAutoPlay('toggle')
	}

	//////// Touch events
	let touchDownX = null
	let touchDownY = null

	function getTouches(evt) {
		return evt.touches
	}

	function handleTouchStart(evt) {
		const firstTouch = getTouches(evt)[0]
		touchDownX = firstTouch.clientX
		touchDownY = firstTouch.clientY
	}

	function handleTouchMove(evt) {
		let deadZone = 10
		let isZoomed = window.visualViewport.scale > viewerState.viewportUnzoomedScale

		if (!touchDownX || !touchDownY || isZoomed) {
			return
		}

		let xUp = evt.touches[0].clientX
		let yUp = evt.touches[0].clientY

		let xDiff = touchDownX - xUp
		let yDiff = touchDownY - yUp

		if (Math.abs(xDiff) < deadZone
				|| Math.abs(yDiff) < deadZone) {
			return
		}

		if (Math.abs(xDiff) > Math.abs(yDiff)) {
			// horizontal distance greater
			if (xDiff > 0) {
				// swiping right
				viewerState.viewedIndex++
				updateViewed(1)
			} else {
				// swiping left
				viewerState.viewedIndex--
				updateViewed(-1)
			}
		} else {
			// vertical distance greater
			if (yDiff > 0) {
				// swiping down
			} else {
				// swiping up
			}
		}
		touchDownX = null
		touchDownY = null
	}

	document.ontouchstart = handleTouchStart // todo: more viewer state
	document.ontouchmove  = handleTouchMove  // todo: more viewer state
}
//#endregion

//#region MARK:boot the UI
buildDom()
resumeSession()
highlightLastDir()
thumbs.loadVisible()
thumbs.loadRandomly()
bindEvents()
borderViewed()
updateFlagButton()
//#endregion
