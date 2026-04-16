import { useEffect, useMemo, useRef, useState } from 'react'
import { io } from 'socket.io-client'

const envApiUrl = import.meta.env.VITE_API_URL || ''
const envSocketUrl = import.meta.env.VITE_SOCKET_URL || ''
const AUTO_REFRESH_MS = 8000
const SETUP_REFRESH_MS = 12000

const pages = ['dashboard', 'drives', 'logs', 'ripper-status', 'settings', 'library', 'history', 'accounts']

const pipelineStages = [
  'lsdvd scan for disc label, track durations, and audio languages',
  'LLM proposes likely title/year, then TMDB candidates are hydrated with runtime metadata',
  'Cross-check scoring validates runtime, label overlap, and optional OMDB/TVDB corroboration',
  'Low-confidence results fall back to conservative LLM naming to avoid false positives',
  'SQLite disc cache stores label-to-title mapping to avoid repeat identification',
]

export default function App() {
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('dvdflix_api_url') || envApiUrl)
  const [socketUrl, setSocketUrl] = useState(localStorage.getItem('dvdflix_socket_url') || envSocketUrl)
  const [apiUrlInput, setApiUrlInput] = useState(apiUrl)
  const [socketUrlInput, setSocketUrlInput] = useState(socketUrl)
  const [theme, setTheme] = useState(localStorage.getItem('dvdflix_theme') || 'dark')
  const [activePage, setActivePage] = useState('dashboard')

  const [setupStatus, setSetupStatus] = useState(null)
  const [setupError, setSetupError] = useState('')
  const [detectedDrives, setDetectedDrives] = useState([])
  const [manualSetupDrives, setManualSetupDrives] = useState(false)
  const [manualSettingsDrives, setManualSettingsDrives] = useState(false)
  const [token, setToken] = useState(localStorage.getItem('dvdflix_token') || '')
  const [message, setMessage] = useState('')
  const [messageType, setMessageType] = useState('') // 'success', 'error', 'info'

  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [setupForm, setSetupForm] = useState({
    username: '',
    password: '',
    settings: {
      MOVIES_PATH: '/library/movies',
      TV_PATH: '/library/tvshows',
      TEMP_RIP_PATH: '/media/dvdflix/tmp',
      DRIVES: '',
      TMDB_API_KEY: '',
      OMDB_API_KEY: '',
      TVDB_API_KEY: '',
      TVDB_PIN: '',
      OLLAMA_URL: 'http://host.docker.internal:11434',
      OLLAMA_MODEL: 'qwen2.5:7b',
      RUNTIME_TOLERANCE_MINUTES: '8',
      IDENTIFY_MIN_CONFIDENCE: '80',
      MAX_IDENTIFY_WORKERS: '1',
      DISC_CACHE_DB: '/app/data/disc_cache.db',
      OPENSUBTITLES_API_KEY: '',
      ENABLE_WEB_SEARCH: 'false',
      SEARXNG_URL: '',
      HANDBRAKE_PRESET: 'default',
      MAKEMKVCON_PATH: 'makemkvcon',
    },
    profile: {
      PROFILE_SERVER: '',
      PROFILE_STORAGE_ROOT: '',
      PROFILE_DRIVE_SR0: 'SR0',
      PROFILE_DRIVE_SR1: 'SR1',
      PROFILE_DRIVE_SR2: 'SR2',
      PROFILE_GPU: 'CPU',
      PROFILE_JELLYFIN_URL: '',
      PROFILE_OLLAMA_MODEL: 'qwen2.5:7b',
      PROFILE_NOTES: '',
    },
  })

  const [settingsDraft, setSettingsDraft] = useState(null)
  const [profileDraft, setProfileDraft] = useState({})
  const [capabilities, setCapabilities] = useState(null)
  const [health, setHealth] = useState(null)
  const [driveStatus, setDriveStatus] = useState({ drives: [], summary: null })
  const [jobs, setJobs] = useState([])
  const [library, setLibrary] = useState({ movies: [], tvshows: [] })
  const [tempFiles, setTempFiles] = useState({ root: '', exists: false, entries: [], summary: { count: 0, file_count: 0, total_bytes: 0 } })
  const [maintenanceTasks, setMaintenanceTasks] = useState([])
  const [maintenanceScope, setMaintenanceScope] = useState('all')
  const [maintenanceBusy, setMaintenanceBusy] = useState(false)
  const [maintenanceAction, setMaintenanceAction] = useState('')
  const [setupLoading, setSetupLoading] = useState(false)
  const [authedLoading, setAuthedLoading] = useState(false)
  const [authedLoaded, setAuthedLoaded] = useState(false)
  const [history, setHistory] = useState([])
  const [accounts, setAccounts] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [newAccountForm, setNewAccountForm] = useState({ username: '', password: '', is_admin: false })
  
  // Manual title override modal
  const [overrideModal, setOverrideModal] = useState(null) // { jobId, jobTitle }
  const [searchQuery, setSearchQuery] = useState('')
  const [searchMediaType, setSearchMediaType] = useState('movie')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [historyEditModal, setHistoryEditModal] = useState(null)
  const authedRefreshInFlight = useRef(false)
  const setupRefreshInFlight = useRef(false)

  const effectiveSocketUrl = socketUrl || apiUrl
  const socket = useMemo(() => io(effectiveSocketUrl, { autoConnect: false, transports: ['websocket', 'polling'] }), [effectiveSocketUrl])
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('dvdflix_theme', theme)
  }, [theme])

  const showMessage = (text, type = 'info') => {
    setMessage(text)
    setMessageType(type)
    setTimeout(() => setMessage(''), 5000)
  }

  const driveButtonLabel = (defaultLabel, actionName) => {
    if (!driveBusy) return defaultLabel
    return driveAction === actionName ? `${defaultLabel}…` : 'Working…'
  }

  const refreshSetupStatus = async () => {
    if (setupRefreshInFlight.current) return
    setupRefreshInFlight.current = true
    setSetupLoading(true)
    if (!apiUrl) {
      showMessage('Backend URL is required', 'error')
      setupRefreshInFlight.current = false
      setSetupLoading(false)
      return
    }
    try {
      const resp = await fetch(`${apiUrl}/api/setup/status`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setSetupStatus(data)
      setSetupError('')
      setDetectedDrives(data?.detected_drives || [])
      if (data?.settings && !settingsDraft) {
        setSettingsDraft(data.settings)
      }
    } catch (err) {
      setSetupError(`Cannot reach ${apiUrl}: ${err.message}`)
    } finally {
      setupRefreshInFlight.current = false
      setSetupLoading(false)
    }
  }

  const fetchAuthedData = async () => {
    if (!token || !apiUrl) return
    if (authedRefreshInFlight.current) return
    authedRefreshInFlight.current = true
    setAuthedLoading(true)
    try {
      const resp = await fetch(`${apiUrl}/api/dashboard`, { headers: authHeaders })
      if (resp.status === 401) {
        setToken('')
        localStorage.removeItem('dvdflix_token')
        return
      }
      const data = await resp.json().catch(() => null)
      if (!resp.ok || !data?.ok) {
        return
      }

      setHealth(data.health || null)
      setJobs(data.jobs || [])
      setLibrary(data.library || { movies: [], tvshows: [] })
      setCapabilities(data.capabilities || null)
      setDriveStatus(data.drives || { drives: [], summary: null })
      const tempData = data.temp_files || { root: '', exists: false, entries: [], summary: { count: 0, file_count: 0, total_bytes: 0 } }
      setTempFiles({
        root: tempData.root || '',
        exists: !!tempData.exists,
        entries: tempData.entries || [],
        summary: tempData.summary || { count: 0, file_count: 0, total_bytes: 0 },
      })
      setMaintenanceTasks((data.maintenance && data.maintenance.tasks) || [])

      if (data.settings?.settings) setSettingsDraft(data.settings.settings)
      if (data.profile?.profile) setProfileDraft(data.profile.profile)
      setHistory((data.history && data.history.history) || [])
      setAccounts((data.accounts && data.accounts.users) || [])
      setCurrentUser(data.accounts?.current_user || null)
      setAuthedLoaded(true)
    } catch {
      // Background polling should be resilient; manual actions surface explicit errors.
    } finally {
      authedRefreshInFlight.current = false
      setAuthedLoading(false)
    }
  }

  useEffect(() => {
    if (apiUrl) refreshSetupStatus()
  }, [apiUrl])

  useEffect(() => {
    if (!token || !effectiveSocketUrl) return
    fetchAuthedData()
    socket.connect()
    socket.on('connect', () => setSocketConnected(true))
    socket.on('disconnect', () => setSocketConnected(false))
    socket.on('job_update', (job) => {
      setJobs((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return [job, ...rest]
      })
    })
    socket.on('drive_update', (status) => {
      if (status) {
        setDriveStatus(status)
      }
    })
    return () => socket.disconnect()
  }, [socket, token, effectiveSocketUrl])

  useEffect(() => {
    if (!apiUrl || token) return
    const timer = setInterval(() => {
      refreshSetupStatus()
    }, SETUP_REFRESH_MS)
    return () => clearInterval(timer)
  }, [apiUrl, token])

  useEffect(() => {
    if (!token || !apiUrl) return
    const timer = setInterval(() => {
      fetchAuthedData()
    }, AUTO_REFRESH_MS)
    return () => clearInterval(timer)
  }, [token, apiUrl])

  const applyBackendUrls = () => {
    const nextApi = (apiUrlInput || '').trim().replace(/\/$/, '')
    const nextSocket = (socketUrlInput || '').trim().replace(/\/$/, '')
    setApiUrl(nextApi)
    setSocketUrl(nextSocket)
    setSetupError('')
    setSetupLoading(true)
    localStorage.setItem('dvdflix_api_url', nextApi)
    localStorage.setItem('dvdflix_socket_url', nextSocket)
  }

  const login = async () => {
    const resp = await fetch(`${apiUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      showMessage(data.error || 'Login failed', 'error')
      return
    }
    setToken(data.token)
    localStorage.setItem('dvdflix_token', data.token)
    showMessage('Login successful', 'success')
  }

  const initializeSetup = async () => {
    const resp = await fetch(`${apiUrl}/api/setup/initialize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(setupForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      showMessage(data.error || 'Setup failed', 'error')
      return
    }
    localStorage.setItem('dvdflix_token', data.token)
    setToken(data.token)
    showMessage('Setup complete', 'success')
    await refreshSetupStatus()
  }

  const detectDrives = async () => {
    try {
      const resp = await fetch(`${apiUrl}/api/setup/detected-drives`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      const drives = data?.drives || []
      setDetectedDrives(drives)
      if (drives.length === 0) {
        setManualSetupDrives(true)
        setManualSettingsDrives(true)
        showMessage('No drives detected inside container. Check Docker device mapping.', 'info')
      } else {
        setManualSetupDrives(false)
        setManualSettingsDrives(false)
        showMessage(`Detected ${drives.length} drive(s)`, 'success')
      }
    } catch (err) {
      showMessage(`Drive detection failed: ${err.message}`, 'error')
    }
  }

  const saveSettings = async () => {
    if (!settingsDraft) return
    const resp = await fetch(`${apiUrl}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(settingsDraft),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      showMessage(data.error || 'Failed to save settings', 'error')
      return
    }
    showMessage('Settings saved', 'success')
    await fetchAuthedData()
    await refreshSetupStatus()
  }

  const formatBytes = (bytes) => {
    const value = Number(bytes || 0)
    if (value < 1024) return `${value} B`
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
    if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
    return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const clearTempFolder = async () => {
    const ok = window.confirm('Delete all files and folders under TEMP_RIP_PATH? This cannot be undone.')
    if (!ok) return

    const resp = await fetch(`${apiUrl}/api/temp-files/cleanup`, {
      method: 'POST',
      headers: { ...authHeaders },
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok || data?.ok === false) {
      showMessage(data.error || `Cleanup completed with errors (${(data?.errors || []).length || 0})`, 'error')
    } else {
      showMessage(`Temp cleanup complete (${data.removed || 0} items removed)`, 'success')
    }
    await fetchAuthedData()
  }

  const runEncodeLibrary = async (scope = 'all') => {
    if (maintenanceBusy) {
      showMessage('Already queueing a maintenance action. Please wait.', 'info')
      return
    }
    setMaintenanceBusy(true)
    setMaintenanceAction(`Queueing encode ${scope}`)
    try {
      const resp = await fetch(`${apiUrl}/api/maintenance/encode-library`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ scope, suffix: '.x265.mkv' }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        showMessage(data.error || 'Failed to queue encode task', 'error')
        return
      }
      showMessage(`Encode task queued successfully for ${scope}`, 'success')
      await fetchAuthedData()
    } finally {
      setMaintenanceBusy(false)
      setMaintenanceAction('')
    }
  }

  const runEncodeItem = async (scope, path) => {
    if (maintenanceBusy) {
      showMessage('Already processing a maintenance action. Please wait.', 'info')
      return
    }
    setMaintenanceBusy(true)
    setMaintenanceAction(`Queueing encode item`)
    try {
      const resp = await fetch(`${apiUrl}/api/maintenance/encode-item`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ scope, path, suffix: '.x265.mkv' }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        showMessage(data.error || `Failed to queue encode for ${path}`, 'error')
        return
      }
      showMessage(`Encode queued for ${path}`, 'success')
      await fetchAuthedData()
    } finally {
      setMaintenanceBusy(false)
      setMaintenanceAction('')
    }
  }

  const runRenameLibrary = async (scope = maintenanceScope) => {
    if (maintenanceBusy) {
      showMessage('Already processing a maintenance action. Please wait.', 'info')
      return
    }
    setMaintenanceBusy(true)
    setMaintenanceAction(`Queueing rename ${scope}`)
    try {
      const resp = await fetch(`${apiUrl}/api/maintenance/rename-library`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ scope }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        showMessage(data.error || 'Failed to queue rename task', 'error')
        return
      }
      showMessage(`Rename task queued successfully for ${scope}`, 'success')
      await fetchAuthedData()
    } finally {
      setMaintenanceBusy(false)
      setMaintenanceAction('')
    }
  }

  const runRenameItem = async (scope, path) => {
    if (maintenanceBusy) {
      showMessage('Already processing a maintenance action. Please wait.', 'info')
      return
    }
    setMaintenanceBusy(true)
    setMaintenanceAction('Queueing rename item')
    try {
      const resp = await fetch(`${apiUrl}/api/maintenance/rename-item`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ scope, path }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        showMessage(data.error || `Failed to queue rename for ${path}`, 'error')
        return
      }
      showMessage(`Rename queued for ${path}`, 'success')
      await fetchAuthedData()
    } finally {
      setMaintenanceBusy(false)
      setMaintenanceAction('')
    }
  }

  const startAll = async () => {
    if (driveBusy) {
      showMessage('Drive action already in progress', 'info')
      return
    }
    setDriveBusy(true)
    setDriveAction('start-all')
    try {
      const resp = await fetch(`${apiUrl}/api/jobs/start-all`, { method: 'POST', headers: authHeaders })
      const data = await resp.json().catch(() => ({}))
      showMessage(resp.ok ? 'Started all drives' : data.error || 'Failed to start all drives', resp.ok ? 'success' : 'error')
    } finally {
      setDriveBusy(false)
      setDriveAction('')
    }
  }

  const startDrive = async (drive) => {
    if (driveBusy) {
      showMessage('Drive action already in progress', 'info')
      return
    }
    setDriveBusy(true)
    setDriveAction(`start-${drive}`)
    try {
      const resp = await fetch(`${apiUrl}/api/jobs/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ drive }),
      })
      const data = await resp.json().catch(() => ({}))
      showMessage(resp.ok ? `Started ${drive}` : (data.error || `Failed to start ${drive}`), resp.ok ? 'success' : 'error')
    } finally {
      setDriveBusy(false)
      setDriveAction('')
    }
  }

  const ejectSelectedDrive = async (drive) => {
    if (driveBusy) {
      showMessage('Drive action already in progress', 'info')
      return
    }
    setDriveBusy(true)
    setDriveAction(`eject-${drive}`)
    try {
      const resp = await fetch(`${apiUrl}/api/drives/eject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ drive }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        showMessage(data.error || data.message || `Failed to eject ${drive}`, 'error')
        return
      }
      showMessage(data.message || `Ejected ${drive}`, 'success')
      await fetchAuthedData()
    } finally {
      setDriveBusy(false)
      setDriveAction('')
    }
  }

  const searchTMDB = async (query, mediaType) => {
    const type = mediaType || searchMediaType
    setSearching(true)
    try {
      const resp = await fetch(`${apiUrl}/api/search/tmdb`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ query, media_type: type }),
      })
      const data = await resp.json()
      setSearchResults(data.ok ? (data.results || []) : [])
      if (!data.ok) showMessage(data.error || 'Search failed', 'error')
    } catch (err) {
      showMessage('Search error: ' + err.message, 'error')
    } finally {
      setSearching(false)
    }
  }

  const overrideJobTitle = async (jobId, title, year, mediaType) => {
    const resp = await fetch(`${apiUrl}/api/jobs/${jobId}/override-title`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ title, year, media_type: mediaType }),
    })
    if (resp.ok) {
      showMessage('Title overridden successfully', 'success')
      setOverrideModal(null)
      setSearchQuery('')
      setSearchResults([])
    } else {
      showMessage('Failed to override title', 'error')
    }
  }

  const saveHistoryCorrection = async () => {
    if (!historyEditModal) return
    const payload = {
      title: historyEditModal.title || '',
      year: historyEditModal.year || '',
      media_type: historyEditModal.media_type || 'movie',
      notes: historyEditModal.notes || '',
    }
    const resp = await fetch(`${apiUrl}/api/history/${historyEditModal.disc_hash}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      showMessage(data.error || 'Failed to update history record', 'error')
      return
    }
    showMessage('History record updated', 'success')
    setHistoryEditModal(null)
    await fetchAuthedData()
  }

  const createAccount = async () => {
    const payload = {
      username: (newAccountForm.username || '').trim(),
      password: newAccountForm.password || '',
      is_admin: !!newAccountForm.is_admin,
    }
    if (!payload.username || !payload.password) {
      showMessage('Username and password are required', 'error')
      return
    }

    const resp = await fetch(`${apiUrl}/api/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(payload),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      showMessage(data.error || 'Failed to create account', 'error')
      return
    }
    showMessage('Account created', 'success')
    setNewAccountForm({ username: '', password: '', is_admin: false })
    await fetchAuthedData()
  }

  const logout = () => {
    setToken('')
    localStorage.removeItem('dvdflix_token')
    showMessage('Logged out', 'info')
  }

  const jobStateColor = (state) => {
    switch (state) {
      case 'complete': return '#10b981'
      case 'failed': return '#ef4444'
      case 'needs_review': return '#f97316'
      case 'ripping': return '#f59e0b'
      case 'encoding': return '#8b5cf6'
      case 'postprocessing': return '#06b6d4'
      case 'canceled': return '#64748b'
      case 'identifying': return '#3b82f6'
      case 'pending': return '#6b7280'
      case 'queued': return '#7c3aed'
      case 'running': return '#4338ca'
      default: return '#999'
    }
  }

  const isJobActive = (state) => ['queued', 'running', 'pending', 'identifying', 'ripping', 'encoding', 'postprocessing'].includes(state)

  const maintenanceButtonLabel = (defaultLabel, actionName) => {
    if (!maintenanceBusy) return defaultLabel
    return maintenanceAction === actionName ? `${defaultLabel}…` : 'Processing…'
  }

  const driveStatusTone = (status) => {
    if (status === 'ready' || status === 'encrypted') return 'ok'
    if (status === 'empty') return 'warn'
    if (status === 'missing' || status === 'error' || status === 'tool-missing') return 'bad'
    return 'info'
  }

  const formatTimestamp = (value) => {
    if (!value) return 'n/a'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString()
  }

  const cancelJob = async (jobId) => {
    const resp = await fetch(`${apiUrl}/api/jobs/${jobId}/cancel`, {
      method: 'POST',
      headers: { ...authHeaders },
    })
    const data = await resp.json().catch(() => ({}))
    showMessage(resp.ok ? 'Cancel requested' : (data.error || 'Failed to cancel job'), resp.ok ? 'info' : 'error')
    await fetchAuthedData()
  }

  const cleanupJobOutput = async (jobId) => {
    const resp = await fetch(`${apiUrl}/api/jobs/${jobId}/cleanup-output`, {
      method: 'POST',
      headers: { ...authHeaders },
    })
    const data = await resp.json().catch(() => ({}))
    showMessage(resp.ok ? (data.message || 'Output cleaned') : (data.error || 'Failed to clean output'), resp.ok ? 'success' : 'error')
    await fetchAuthedData()
  }

  const cancelMaintenanceTask = async (taskId) => {
    const resp = await fetch(`${apiUrl}/api/maintenance/tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: { ...authHeaders },
    })
    const data = await resp.json().catch(() => ({}))
    showMessage(resp.ok ? 'Task cancel requested' : (data.error || 'Failed to cancel task'), resp.ok ? 'info' : 'error')
    await fetchAuthedData()
  }

  const allLogs = useMemo(() => {
    const ripLogs = (jobs || []).flatMap((job) => {
      const lines = Array.isArray(job.logs) ? job.logs : []
      return lines.map((line) => ({
        ts: line?.startsWith('[') ? line.slice(1, 9) : '',
        source: `rip:${job.drive || 'unknown'}`,
        state: job.state || 'unknown',
        text: line,
      }))
    })

    const taskLogs = (maintenanceTasks || []).flatMap((task) => {
      const lines = Array.isArray(task.logs) ? task.logs : []
      return lines.map((line) => ({
        ts: line?.startsWith('[') ? line.slice(1, 9) : '',
        source: task.kind || 'task',
        state: task.state || 'unknown',
        text: line,
      }))
    })

    return [...ripLogs, ...taskLogs].slice(-1000)
  }, [jobs, maintenanceTasks])

  const dashboardItems = useMemo(() => {
    const itemMap = new Map()
    ;(jobs || []).forEach((job) => {
      itemMap.set(job.id, {
        ...job,
        kind: job.drive ? 'rip' : 'job',
      })
    })

    ;(maintenanceTasks || []).forEach((task) => {
      if (itemMap.has(task.id)) return
      itemMap.set(task.id, {
        id: task.id,
        drive: '',
        title: task.title || task.kind,
        state: task.state || 'queued',
        progress: Number(task.progress || (task.state === 'complete' ? 100 : task.state === 'failed' ? 100 : task.state === 'running' ? 50 : 0)),
        logs: task.logs || [],
        error: task.error || '',
        output_path: task.output_path || '',
        kind: 'maintenance',
        taskKind: task.kind,
        updated_at: task.updated_at,
      })
    })

    return Array.from(itemMap.values()).sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
  }, [jobs, maintenanceTasks])

  const activeDashboardCount = dashboardItems.filter((item) => isJobActive(item.state)).length

  // Connection Setup Page
  if (!setupStatus) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🎬 DvDRip</h1>
            <p>Self-hosted DVD Operations Console</p>
          </div>
          
          <div className="setup-card">
            <h2>Backend Connection</h2>
            <div className="form-group">
              <label>API URL</label>
              <input 
                type="text"
                placeholder="http://localhost:7272"
                value={apiUrlInput}
                onChange={(e) => setApiUrlInput(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Socket URL (optional)</label>
              <input 
                type="text"
                placeholder="Leave empty to use API URL"
                value={socketUrlInput}
                onChange={(e) => setSocketUrlInput(e.target.value)}
              />
            </div>
            <button className="btn-primary" onClick={applyBackendUrls} disabled={setupLoading}>
              {setupLoading ? 'Connecting…' : 'Connect'}
            </button>
            {setupLoading && <div className="alert alert-info">Connecting to backend…</div>}
            {setupError && <div className="alert alert-error">{setupError}</div>}
          </div>
        </div>
      </div>
    )
  }

  // First-Run Setup
  if (!setupStatus.configured) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🎬 DvDRip Setup</h1>
            <p>Configure Your Ripping System</p>
          </div>

          <div className="setup-card">
            <h2>Admin Account</h2>
            <div className="form-group">
              <label>Username</label>
              <input value={setupForm.username} onChange={(e) => setSetupForm({ ...setupForm, username: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={setupForm.password} onChange={(e) => setSetupForm({ ...setupForm, password: e.target.value })} />
            </div>
          </div>

          <div className="setup-cards-row">
            <div className="setup-card">
              <h2>🔧 Runtime Settings</h2>
              <div className="form-group">
                <label>Movies Path</label>
                <input value={setupForm.settings.MOVIES_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MOVIES_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TV Path</label>
                <input value={setupForm.settings.TV_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TV_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Temp Rip Path</label>
                <input value={setupForm.settings.TEMP_RIP_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TEMP_RIP_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TMDB API Key</label>
                <input type="password" value={setupForm.settings.TMDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TMDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>OMDB API Key</label>
                <input type="password" value={setupForm.settings.OMDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OMDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TVDB API Key</label>
                <input type="password" value={setupForm.settings.TVDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TVDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TVDB PIN</label>
                <input value={setupForm.settings.TVDB_PIN} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TVDB_PIN: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>OpenSubtitles API Key</label>
                <input type="password" value={setupForm.settings.OPENSUBTITLES_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OPENSUBTITLES_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Drives (Auto-Detect)</label>
                <div className="inline-actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={detectDrives}
                  >
                    Detect Drives
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      setSetupForm({
                        ...setupForm,
                        settings: {
                          ...setupForm.settings,
                          DRIVES: detectedDrives.join(','),
                        },
                      })
                    }
                    disabled={detectedDrives.length === 0}
                  >
                    Use Detected
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setManualSetupDrives((v) => !v)}
                  >
                    {manualSetupDrives ? 'Hide Manual Entry' : 'Manual Entry'}
                  </button>
                </div>
                {manualSetupDrives && (
                  <input
                    placeholder="/dev/sr0,/dev/sr1"
                    value={setupForm.settings.DRIVES}
                    onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, DRIVES: e.target.value } })}
                  />
                )}
                <small className="field-help">
                  Leave blank to auto-detect `/dev/sr*` drives. Detected now: {detectedDrives.length ? detectedDrives.join(', ') : 'none'}
                </small>
              </div>
            </div>

            <div className="setup-card">
              <h2>🌐 Ollama Settings</h2>
              <div className="form-group">
                <label>Ollama URL</label>
                <input value={setupForm.settings.OLLAMA_URL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OLLAMA_URL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Ollama Model</label>
                <input value={setupForm.settings.OLLAMA_MODEL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OLLAMA_MODEL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Confidence Threshold</label>
                <input type="number" min="0" max="100" value={setupForm.settings.IDENTIFY_MIN_CONFIDENCE} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, IDENTIFY_MIN_CONFIDENCE: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Runtime Tolerance Minutes</label>
                <input type="number" min="0" max="60" value={setupForm.settings.RUNTIME_TOLERANCE_MINUTES} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, RUNTIME_TOLERANCE_MINUTES: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Max Identify Workers</label>
                <input type="number" min="1" max="8" value={setupForm.settings.MAX_IDENTIFY_WORKERS} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MAX_IDENTIFY_WORKERS: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Disc Cache DB Path</label>
                <input value={setupForm.settings.DISC_CACHE_DB} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, DISC_CACHE_DB: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Enable Web Search</label>
                <select value={setupForm.settings.ENABLE_WEB_SEARCH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, ENABLE_WEB_SEARCH: e.target.value } })}>
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              </div>
              <div className="form-group">
                <label>Searxng URL</label>
                <input value={setupForm.settings.SEARXNG_URL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, SEARXNG_URL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>HandBrake Preset</label>
                <select value={setupForm.settings.HANDBRAKE_PRESET} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, HANDBRAKE_PRESET: e.target.value } })}>
                  <option value="default">default (all tracks)</option>
                  <option value="standard">standard (main feature)</option>
                </select>
              </div>
              <div className="form-group">
                <label>MakeMKV Command Path</label>
                <input value={setupForm.settings.MAKEMKVCON_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MAKEMKVCON_PATH: e.target.value } })} />
                <small className="field-help">Default: `makemkvcon`</small>
              </div>
            </div>
          </div>

          <div className="setup-card">
            <h2>ℹ️ Docker-Level Requirements</h2>
            <p className="field-help">
              Keys and runtime behavior are fully configurable in this UI. Docker still needs host-level mappings for optical devices and media folders.
            </p>
            <p className="field-help">
              Required at deploy time in Dockge: `HOST_MOVIES_PATH`, `HOST_TV_PATH`, `HOST_TEMP_RIP_PATH`, and `/dev/sr*` device mapping.
            </p>
          </div>

          <button className="btn-primary full-width" onClick={initializeSetup}>
            Complete Setup
          </button>
          {message && <div className={`alert alert-${messageType}`}>{message}</div>}
        </div>
      </div>
    )
  }

  // Login
  if (!token) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🔐 DvDRip Login</h1>
            <p>Enter your credentials</p>
          </div>

          <div className="setup-card">
            <div className="form-group">
              <label>Username</label>
              <input value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
            </div>
            <button className="btn-primary full-width" onClick={login}>
              Log In
            </button>
            {message && <div className={`alert alert-${messageType}`}>{message}</div>}
          </div>
        </div>
      </div>
    )
  }

  // Main App
  return (
    <div className="page main-app">
      <header className="top-bar">
        <div className="top-bar-left">
          <h1>🎬 DvDRip</h1>
        </div>
        <div className="top-bar-center">
          <nav className="nav-tabs">
            {pages.map((p) => (
              <button
                key={p}
                className={`nav-tab ${activePage === p ? 'active' : ''}`}
                onClick={() => setActivePage(p)}
                title={`View the ${p.replace(/-/g, ' ')} page`}
              >
                {p === 'dashboard' && '📊 Dashboard'}
                {p === 'drives' && '💿 Drives'}
                {p === 'logs' && '🧾 Logs'}
                {p === 'ripper-status' && '⚙️ Ripper'}
                {p === 'settings' && '⚡ Settings'}
                {p === 'library' && '📚 Library'}
                {p === 'history' && '🕘 History'}
                {p === 'accounts' && '👤 Accounts'}
              </button>
            ))}
          </nav>
        </div>
        <div className="top-bar-right" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 10px',
              height: '32px',
              borderRadius: '999px',
              backgroundColor: socketConnected ? '#10b981' : '#f59e0b',
              color: '#fff',
              fontSize: '0.9rem',
            }}
            title={socketConnected ? 'Live websocket connected' : 'Socket disconnected'}
          >
            {socketConnected ? 'Live' : 'Offline'}
          </span>
          <button className="btn-icon" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Toggle theme">
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
          <button className="btn-secondary" onClick={logout} title="Sign out of the dashboard">Logout</button>
        </div>
      </header>

      {activePage === 'dashboard' && (
        <div className="content">
          <div className="grid-2 grid-gaps">
            <div className="card">
              <h2>🚀 Quick Actions</h2>
              <button className="btn-primary full-width" onClick={startAll} disabled={driveBusy} title="Start ripping on every available drive">
                {driveButtonLabel('Start All Drives', 'start-all')}
              </button>
              <div className="drive-buttons">
                {(health?.drives || []).map((d) => (
                  <button key={d} className="btn-secondary" onClick={() => startDrive(d)} disabled={driveBusy} title={`Start ripping on drive ${d}`}>
                    {driveButtonLabel(d, `start-${d}`)}
                  </button>
                ))}
              </div>
              {driveBusy && (
                <div className="alert alert-info" style={{ marginTop: '12px' }}>
                  {driveAction ? `${driveAction.replace(/-/g, ' ')}…` : 'Processing drive action...'}
                </div>
              )}
            </div>

            <div className="card">
              <h2>📍 System Info</h2>
              <div className="info-list">
                <div className="info-item">
                  <span className="label">Movies Path</span>
                  <span className="value">{health?.movies_path}</span>
                </div>
                <div className="info-item">
                  <span className="label">TV Path</span>
                  <span className="value">{health?.tv_path}</span>
                </div>
                <div className="info-item">
                  <span className="label">Active Drives</span>
                  <span className="value">{driveStatus?.summary?.total ?? (health?.drives?.length || 0)}</span>
                </div>
                <div className="info-item">
                  <span className="label">Drives With Disc</span>
                  <span className="value">{driveStatus?.summary?.with_disc ?? 0}</span>
                </div>
                <div className="info-item">
                  <span className="label">Active Jobs</span>
                  <span className="value">{activeDashboardCount}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <h2>📋 Recent Jobs</h2>
            {dashboardItems.length === 0 ? (
              <p className="empty-state">No jobs yet. Insert a disc or queue maintenance tasks.</p>
            ) : (
              <div className="jobs-list">
                {dashboardItems.slice(0, 8).map((job) => (
                  <div key={job.id} className="job-item">
                    <div className="job-header">
                      <span className="job-drive">{job.drive || (job.kind === 'maintenance' ? job.taskKind || 'maintenance' : 'system')}</span>
                      <span className="job-title">{job.title || job.disc_label || 'Unknown'}</span>
                      <span className="job-state" style={{ backgroundColor: jobStateColor(job.state) }}>
                        {job.state}
                      </span>
                      {job.kind === 'maintenance' && <span className="badge badge-info" style={{ marginLeft: '8px' }}>Maintenance</span>}
                    </div>
                    <div className="job-progress-wrap">
                      <div className="job-progress-bar">
                        <div className="job-progress-fill" style={{ width: `${Math.max(0, Math.min(100, Number(job.progress || 0)))}%` }} />
                      </div>
                      <div className="job-progress-label">{Math.max(0, Math.min(100, Number(job.progress || 0)))}%</div>
                    </div>
                    <div className="job-stage-line">
                      {Array.isArray(job.logs) && job.logs.length > 0 ? job.logs[job.logs.length - 1] : 'No logs yet'}
                    </div>
                    {job.error && <div className="job-error">⚠️ {job.error}</div>}
                    <div className="inline-actions" style={{ marginTop: '8px' }}>
                      {isJobActive(job.state) && (
                        <button className="btn-secondary" onClick={() => cancelJob(job.id)} title="Stop this job and free the drive if possible">
                          Terminate Job
                        </button>
                      )}
                      {job.output_path && (
                        <button className="btn-secondary" onClick={() => cleanupJobOutput(job.id)} title="Remove temporary output for this job">
                          Cleanup Output
                        </button>
                      )}
                    </div>
                    {(job.state === 'identifying' || job.state === 'needs_review') && (
                      <button
                        className="btn-secondary"
                        onClick={() => setOverrideModal({ jobId: job.id, jobTitle: job.title || job.disc_label })}
                        title="Open manual review modal to identify and move this job"
                      >
                        🔍 Manual Identify & Move
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'drives' && (
        <div className="content">
          <div className="card drive-shell">
            <div className="drive-shell-header">
              <div>
                <h2>Optical Drive Bay</h2>
                <p className="drive-shell-subtitle">Live tray state, rip activity, and control actions for each mounted optical device.</p>
              </div>
              <div className="drive-shell-header-actions">
                <button className="btn-secondary" onClick={fetchAuthedData} disabled={authedLoading}>
                  {authedLoading ? 'Refreshing…' : 'Refresh Drives'}
                </button>
                <span className="pill-value">{driveStatus?.summary?.total ?? driveStatus.drives.length}</span>
              </div>
            </div>
            <div className="drive-summary-pill">
              <span className="pill-label">With Disc</span>
              <span className="pill-value">{driveStatus?.summary?.with_disc ?? 0}</span>
            </div>
            <div className="drive-summary-pill">
              <span className="pill-label">Readable</span>
              <span className="pill-value">{driveStatus?.summary?.readable ?? 0}</span>
            </div>
            <div className="drive-summary-pill">
              <span className="pill-label">Empty</span>
              <span className="pill-value">{driveStatus?.summary?.empty ?? 0}</span>
            </div>

            {driveStatus.drives.length === 0 ? (
              <p className="empty-state">No drives detected.</p>
            ) : (
              <div className="drive-grid drive-grid-upgraded">
                {driveStatus.drives.map((d) => {
                  const driveJobs = jobs.filter((j) => j.drive === d.drive)
                  const activeJob = driveJobs.find((j) => isJobActive(j.state))
                  const latestJob = driveJobs[0]
                  const latestLog = Array.isArray(activeJob?.logs) && activeJob.logs.length > 0 ? activeJob.logs[activeJob.logs.length - 1] : ''
                  const progress = Math.max(0, Math.min(100, Number(activeJob?.progress || 0)))
                  const tone = driveStatusTone(d.status)

                  return (
                    <div key={`drive-card-${d.drive}`} className={`drive-card-upgraded tone-${tone}`}>
                      <div className="drive-card-topline">
                        <span className="drive-name">{d.drive}</span>
                        <span className={`badge ${tone}`}>{d.status}</span>
                      </div>

                      <div className="drive-visual-row">
                        <div className={`drive-disc-visual ${d.has_disc ? 'has-disc' : 'no-disc'} ${activeJob ? 'is-active' : ''}`} title={activeJob ? `${activeJob.state} in progress` : 'idle'}>
                          <span className="disc-ring outer" />
                          <span className="disc-ring middle" />
                          <span className="disc-ring inner" />
                          <span className="disc-core" />
                        </div>
                        <div className="drive-quick-meta">
                          <div className="drive-meta-line"><span>Disc</span><strong>{d.has_disc ? 'Loaded' : 'Empty'}</strong></div>
                          <div className="drive-meta-line"><span>Readable</span><strong>{d.readable ? 'Yes' : 'No'}</strong></div>
                          <div className="drive-meta-line"><span>Source</span><strong>{d.source || 'n/a'}</strong></div>
                          <div className="drive-meta-line"><span>Device</span><strong>{d.exists ? 'Present' : 'Missing'}</strong></div>
                        </div>
                      </div>

                      <div className="job-stage-line drive-detail-line">{d.detail}</div>

                      {activeJob ? (
                        <div className="drive-active-job">
                          <div className="drive-job-head">
                            <span className="drive-job-state">{activeJob.state}</span>
                            <span className="drive-job-progress">{progress}%</span>
                          </div>
                          <div className="job-progress-bar">
                            <div className="job-progress-fill" style={{ width: `${progress}%` }} />
                          </div>
                          <div className="job-stage-line">{latestLog || activeJob.title || activeJob.disc_label || 'Working...'}</div>
                        </div>
                      ) : (
                        <div className="drive-last-job">
                          <span className="drive-last-job-label">Last Job</span>
                          <span className="drive-last-job-value">{latestJob ? `${latestJob.state} • ${latestJob.title || latestJob.disc_label || 'Unknown'}` : 'No job yet'}</span>
                          <span className="drive-last-job-time">{latestJob ? formatTimestamp(latestJob.updated_at) : 'n/a'}</span>
                        </div>
                      )}

                              <div className="inline-actions drive-actions-row">
                        <button className="btn-secondary" onClick={() => startDrive(d.drive)} disabled={driveBusy}>
                          {driveButtonLabel('Start', `start-${d.drive}`)}
                        </button>
                        <button className="btn-secondary" onClick={() => ejectSelectedDrive(d.drive)} disabled={driveBusy}>
                          {driveButtonLabel('Eject', `eject-${d.drive}`)}
                        </button>
                        {activeJob && <button className="btn-secondary" onClick={() => cancelJob(activeJob.id)}>Terminate</button>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'logs' && (
        <div className="content">
          <div className="card">
            <h2>🧾 Unified Logs</h2>
            <div className="inline-actions" style={{ marginBottom: '10px' }}>
              <button className="btn-secondary" onClick={fetchAuthedData}>Refresh Logs</button>
            </div>
            {allLogs.length === 0 ? (
              <p className="empty-state">No logs yet.</p>
            ) : (
              <div className="job-log-box" style={{ maxHeight: '520px' }}>
                {allLogs.map((entry, idx) => (
                  <div key={`log-${idx}`} className="job-log-line">
                    [{entry.source}] {entry.text}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'ripper-status' && (
        <div className="content">
          <div className="card">
            <h2>🔧 Ripper Health</h2>
            <div className="health-grid">
              <div className="health-item">
                <span className="label">Overall</span>
                <span className={`badge ${capabilities?.ripper_ready ? 'ok' : 'bad'}`}>
                  {capabilities?.ripper_ready ? '✓ Ready' : '✗ Issues'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">lsdvd</span>
                <span className={`badge ${capabilities?.tools?.lsdvd ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.lsdvd ? '✓' : '✗'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">makemkvcon</span>
                <span className={`badge ${capabilities?.tools?.makemkvcon ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.makemkvcon ? '✓' : '✗'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">eject</span>
                <span className={`badge ${capabilities?.tools?.eject ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.eject ? '✓' : '✗'}
                </span>
              </div>
            </div>
          </div>

          {capabilities?.issues?.length > 0 && (
            <div className="card card-warning">
              <h2>⚠️ Issues</h2>
              <ul>
                {capabilities.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h2>💡 Setup Hints</h2>
            <ul className="hints-list">
              {capabilities?.hints?.map((hint, i) => (
                <li key={i}>{hint}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>💽 Drive Status</h2>
            <div className="inline-actions" style={{ marginBottom: '10px' }}>
              <button className="btn-secondary" onClick={fetchAuthedData}>Refresh</button>
            </div>
            {driveStatus.drives.length === 0 ? (
              <p className="empty-state">No drives detected.</p>
            ) : (
              <div className="drive-status-list">
                {driveStatus.drives.map((d) => (
                  <div className="drive-status-item" key={`status-${d.drive}`}>
                    <div>
                      <div className="drive-status-title">{d.drive}</div>
                      <div className="drive-status-meta">{d.detail}</div>
                    </div>
                    <div className="drive-status-actions">
                      <span className={`badge ${d.status === 'ready' ? 'ok' : d.status === 'empty' ? 'warn' : 'bad'}`}>
                        {d.status}
                      </span>
                      <button className="btn-secondary" onClick={() => ejectSelectedDrive(d.drive)}>
                        Eject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <h2>🛠️ Post-Rip Pipeline</h2>
            <div className="form-group">
              <label>Scope</label>
              <select value={maintenanceScope} onChange={(e) => setMaintenanceScope(e.target.value)}>
                <option value="all">all (movies + tv)</option>
                <option value="movies">movies only</option>
                <option value="tv">tv only</option>
              </select>
            </div>
            <div className="inline-actions">
              <button className="btn-secondary" onClick={runEncodeLibrary} title="Queue a background encode job for the selected library scope">
                Queue Encode Library
              </button>
              <button className="btn-secondary" onClick={runRenameLibrary} title="Queue a background rename job for the selected library scope">
                Queue Rename Library
              </button>
              <button className="btn-secondary" onClick={fetchAuthedData} title="Refresh maintenance task status from the backend">
                Refresh Tasks
              </button>
            </div>

            {maintenanceTasks.length === 0 ? (
              <p className="empty-state">No maintenance tasks yet.</p>
            ) : (
              <div className="jobs-list" style={{ marginTop: '12px' }}>
                {maintenanceTasks.slice(0, 10).map((task) => (
                  <div key={task.id} className="job-item">
                    <div className="job-header">
                      <span className="job-drive">{task.kind}</span>
                      <span className="job-title">{task.id}</span>
                      <span className="job-state" style={{ backgroundColor: jobStateColor(task.state === 'running' ? 'ripping' : task.state === 'complete' ? 'complete' : task.state === 'failed' ? 'failed' : 'pending') }}>
                        {task.state}
                      </span>
                    </div>
                    {Array.isArray(task.logs) && task.logs.length > 0 && (
                      <div className="job-log-box">
                        {task.logs.slice(-80).map((line, idx) => (
                          <div key={`${task.id}-line-${idx}`} className="job-log-line">{line}</div>
                        ))}
                      </div>
                    )}
                    <div className="inline-actions" style={{ marginTop: '8px' }}>
                      {(task.state === 'queued' || task.state === 'running') && (
                        <button className="btn-secondary" onClick={() => cancelMaintenanceTask(task.id)}>
                          Terminate Task
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'settings' && (
        <div className="content">
          <div className="card">
            <h2>⚙️ Runtime Settings</h2>
            {settingsDraft && (
              <>
                <div className="form-grid">
                  <div className="form-group">
                    <label>Movies Path</label>
                    <input value={settingsDraft.MOVIES_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, MOVIES_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TV Path</label>
                    <input value={settingsDraft.TV_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TV_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Temp Rip Path</label>
                    <input value={settingsDraft.TEMP_RIP_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TEMP_RIP_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Drives (Auto-Detect)</label>
                    <div className="inline-actions">
                      <button type="button" className="btn-secondary" onClick={detectDrives}>
                        Detect Drives
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setSettingsDraft({ ...settingsDraft, DRIVES: detectedDrives.join(',') })}
                        disabled={detectedDrives.length === 0}
                      >
                        Use Detected
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setManualSettingsDrives((v) => !v)}
                      >
                        {manualSettingsDrives ? 'Hide Manual Entry' : 'Manual Entry'}
                      </button>
                    </div>
                    {manualSettingsDrives && (
                      <input
                        placeholder="/dev/sr0,/dev/sr1"
                        value={settingsDraft.DRIVES || ''}
                        onChange={(e) => setSettingsDraft({ ...settingsDraft, DRIVES: e.target.value })}
                      />
                    )}
                    <small className="field-help">
                      Current detection: {detectedDrives.length ? detectedDrives.join(', ') : 'none'}
                    </small>
                  </div>
                  <div className="form-group">
                    <label>TMDB API Key</label>
                    <input type="password" value={settingsDraft.TMDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TMDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>OMDB API Key</label>
                    <input type="password" value={settingsDraft.OMDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OMDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TVDB API Key</label>
                    <input type="password" value={settingsDraft.TVDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TVDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TVDB PIN</label>
                    <input value={settingsDraft.TVDB_PIN || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TVDB_PIN: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>OpenSubtitles API Key</label>
                    <input type="password" value={settingsDraft.OPENSUBTITLES_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OPENSUBTITLES_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Ollama URL</label>
                    <input value={settingsDraft.OLLAMA_URL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OLLAMA_URL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Ollama Model</label>
                    <input value={settingsDraft.OLLAMA_MODEL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OLLAMA_MODEL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Runtime Tolerance Minutes</label>
                    <input type="number" min="0" max="60" value={settingsDraft.RUNTIME_TOLERANCE_MINUTES || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, RUNTIME_TOLERANCE_MINUTES: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Confidence Threshold</label>
                    <input type="number" min="0" max="100" value={settingsDraft.IDENTIFY_MIN_CONFIDENCE || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, IDENTIFY_MIN_CONFIDENCE: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Max Identify Workers</label>
                    <input type="number" min="1" max="8" value={settingsDraft.MAX_IDENTIFY_WORKERS || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, MAX_IDENTIFY_WORKERS: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Disc Cache DB Path</label>
                    <input value={settingsDraft.DISC_CACHE_DB || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, DISC_CACHE_DB: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Enable Web Search</label>
                    <select value={settingsDraft.ENABLE_WEB_SEARCH || 'false'} onChange={(e) => setSettingsDraft({ ...settingsDraft, ENABLE_WEB_SEARCH: e.target.value })}>
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Searxng URL</label>
                    <input value={settingsDraft.SEARXNG_URL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, SEARXNG_URL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>HandBrake Preset</label>
                    <select value={settingsDraft.HANDBRAKE_PRESET || 'default'} onChange={(e) => setSettingsDraft({ ...settingsDraft, HANDBRAKE_PRESET: e.target.value })}>
                      <option value="default">default (all tracks)</option>
                      <option value="standard">standard (main feature)</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>DVD HandBrake Preset</label>
                    <select value={settingsDraft.HANDBRAKE_PRESET_DVD || 'default'} onChange={(e) => setSettingsDraft({ ...settingsDraft, HANDBRAKE_PRESET_DVD: e.target.value })}>
                      <option value="default">default</option>
                      <option value="standard">standard</option>
                      <option value="high">high</option>
                      <option value="fast">fast</option>
                      <option value="ultrafast">ultrafast</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Blu-ray HandBrake Preset</label>
                    <select value={settingsDraft.HANDBRAKE_PRESET_BLURAY || 'high'} onChange={(e) => setSettingsDraft({ ...settingsDraft, HANDBRAKE_PRESET_BLURAY: e.target.value })}>
                      <option value="default">default</option>
                      <option value="standard">standard</option>
                      <option value="high">high</option>
                      <option value="fast">fast</option>
                      <option value="ultrafast">ultrafast</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>MakeMKV Command Path</label>
                    <input value={settingsDraft.MAKEMKVCON_PATH || 'makemkvcon'} onChange={(e) => setSettingsDraft({ ...settingsDraft, MAKEMKVCON_PATH: e.target.value })} />
                  </div>
                </div>
                <button className="btn-primary" onClick={saveSettings}>
                  Save Settings
                </button>
                {message && <div className={`alert alert-${messageType}`}>{message}</div>}
              </>
            )}
          </div>
        </div>
      )}

      {activePage === 'library' && (
        <div className="content">
          <div className="card" style={{ marginBottom: '16px' }}>
            <div className="card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <h2>📚 Media Library</h2>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn-secondary" onClick={fetchAuthedData} disabled={authedLoading}>
                  {authedLoading ? 'Refreshing…' : 'Refresh Library'}
                </button>
                <button className="btn-secondary" onClick={() => runEncodeLibrary('all')} disabled={maintenanceBusy || authedLoading}>
                  {maintenanceButtonLabel('Batch encode all', 'Queueing encode all')}
                </button>
                <button className="btn-secondary" onClick={() => runRenameLibrary('all')} disabled={maintenanceBusy || authedLoading}>
                  {maintenanceButtonLabel('Batch rename all', 'Queueing rename all')}
                </button>
              </div>
            </div>
            {authedLoading && !maintenanceBusy && (
              <div className="alert alert-info" style={{ marginTop: '12px' }}>
                Loading library data…
              </div>
            )}
            {maintenanceBusy && (
              <div className="alert alert-info" style={{ marginTop: '12px' }}>
                {maintenanceAction || 'Maintenance action in progress...'}
              </div>
            )}
            <div className="info-list" style={{ marginTop: '12px' }}>
              <div className="info-item">
                <span className="label">Movies path</span>
                <span className="value">{library.movies_path || 'n/a'}</span>
              </div>
              <div className="info-item">
                <span className="label">Movies path exists</span>
                <span className="value">{library.movies_path_exists ? 'Yes' : 'No'}</span>
              </div>
              <div className="info-item">
                <span className="label">TV path</span>
                <span className="value">{library.tv_path || 'n/a'}</span>
              </div>
              <div className="info-item">
                <span className="label">TV path exists</span>
                <span className="value">{library.tv_path_exists ? 'Yes' : 'No'}</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <h2>🎬 Movies ({library.movies.length})</h2>
              <button className="btn-secondary" onClick={() => runEncodeLibrary('movies')} disabled={maintenanceBusy || authedLoading}>
                {maintenanceButtonLabel('Batch encode movies', 'Queueing encode movies')}
              </button>
              <button className="btn-secondary" onClick={() => runRenameLibrary('movies')} disabled={maintenanceBusy || authedLoading}>
                {maintenanceButtonLabel('Batch rename movies', 'Queueing rename movies')}
              </button>
            </div>
            {library.movies.length === 0 && !library.movies_path_exists ? (
              <p className="empty-state">{authedLoading ? 'Loading movies…' : 'Movies path is not available in the container.'}</p>
            ) : (
              <div className="gallery-grid">
                {library.movies.map((item, i) => (
                  <div key={`${item.path}-${i}`} className="media-card">
                    <div className="media-card-poster">
                      {item.poster ? (
                        <img src={item.poster} alt={`${item.title} poster`} />
                      ) : (
                        <div className="media-card-placeholder">No poster</div>
                      )}
                    </div>
                    <div className="media-card-body">
                      <div className="media-card-title-row">
                        <h3>{item.title}{item.year ? ` (${item.year})` : ''}</h3>
                        {item.needs_encode && <span className="badge badge-warning">Encode</span>}
                        {item.needs_rename && <span className="badge badge-info">Rename</span>}
                      </div>
                      <p className="media-card-overview">{item.overview || item.path}</p>
                      <div className="media-card-meta">
                        <span>{item.file_count} file{item.file_count === 1 ? '' : 's'}</span>
                        {item.rating ? <span>★ {item.rating}</span> : null}
                      </div>
                      <div className="media-card-actions">
                        <button className="btn-secondary" onClick={() => runEncodeItem('movies', item.path)} disabled={maintenanceBusy || authedLoading} title={`Encode this library item: ${item.path}`}>
                          {maintenanceButtonLabel('Encode', 'Queueing encode item')}
                        </button>
                        <button className="btn-secondary" onClick={() => runRenameItem('movies', item.path)} disabled={maintenanceBusy || authedLoading} title={`Rename this library item: ${item.path}`}>
                          {maintenanceButtonLabel('Rename', 'Queueing rename item')}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ marginTop: '16px' }}>
            <div className="card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
              <h2>📺 TV Shows ({library.tvshows.length})</h2>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn-secondary" onClick={() => runEncodeLibrary('tv')} disabled={maintenanceBusy || authedLoading}>
                  {maintenanceButtonLabel('Batch encode TV shows', 'Queueing encode tv')}
                </button>
                <button className="btn-secondary" onClick={() => runRenameLibrary('tv')} disabled={maintenanceBusy || authedLoading}>
                  {maintenanceButtonLabel('Batch rename TV shows', 'Queueing rename tv')}
                </button>
              </div>
            </div>
            {library.tvshows.length === 0 && !library.tv_path_exists ? (
              <p className="empty-state">{authedLoading ? 'Loading TV shows…' : 'TV path is not available in the container.'}</p>
            ) : (
              <div className="gallery-grid">
                {library.tvshows.map((item, i) => (
                  <div key={`${item.path}-${i}`} className="media-card">
                    <div className="media-card-poster">
                      {item.poster ? (
                        <img src={item.poster} alt={`${item.title} poster`} />
                      ) : (
                        <div className="media-card-placeholder">No poster</div>
                      )}
                    </div>
                    <div className="media-card-body">
                      <div className="media-card-title-row">
                        <h3>{item.title}{item.year ? ` (${item.year})` : ''}</h3>
                        {item.needs_encode && <span className="badge badge-warning">Encode</span>}
                        {item.needs_rename && <span className="badge badge-info">Rename</span>}
                      </div>
                      <p className="media-card-overview">{item.overview || item.path}</p>
                      <div className="media-card-meta">
                        <span>{item.file_count} file{item.file_count === 1 ? '' : 's'}</span>
                        {item.rating ? <span>★ {item.rating}</span> : null}
                      </div>
                      <div className="media-card-actions">
                        <button className="btn-secondary" onClick={() => runEncodeItem('tv', item.path)} disabled={maintenanceBusy || authedLoading}>
                          {maintenanceButtonLabel('Encode', 'Queueing encode item')}
                        </button>
                        <button className="btn-secondary" onClick={() => runRenameItem('tv', item.path)} disabled={maintenanceBusy || authedLoading}>
                          {maintenanceButtonLabel('Rename', 'Queueing rename item')}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <h2>🧪 Temp Rip Folder ({tempFiles.summary?.count || 0} items)</h2>
            <div className="info-list" style={{ marginBottom: '12px' }}>
              <div className="info-item">
                <span className="label">Path</span>
                <span className="value">{tempFiles.root || 'n/a'}</span>
              </div>
              <div className="info-item">
                <span className="label">Files</span>
                <span className="value">{tempFiles.summary?.file_count || 0}</span>
              </div>
              <div className="info-item">
                <span className="label">Total Size</span>
                <span className="value">{formatBytes(tempFiles.summary?.total_bytes || 0)}</span>
              </div>
            </div>
            <div className="inline-actions" style={{ marginBottom: '12px' }}>
              <button className="btn-secondary" onClick={fetchAuthedData}>Refresh Temp</button>
              <button className="btn-secondary" onClick={clearTempFolder}>Clear Temp Folder</button>
            </div>
            {tempFiles.entries.length === 0 ? (
              <p className="empty-state">No temp files found.</p>
            ) : (
              <div className="file-list">
                {tempFiles.entries.slice(0, 200).map((entry, i) => (
                  <div key={`${entry.path}-${i}`} className="file-item">
                    {entry.is_dir ? '[dir] ' : ''}{entry.path}{!entry.is_dir ? ` (${formatBytes(entry.size)})` : ''}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'history' && (
        <div className="content">
          <div className="card">
            <h2>🕘 Ripped Disc History ({history.length})</h2>
            {history.length === 0 ? (
              <p className="empty-state">No completed rips have been recorded yet.</p>
            ) : (
              <div className="history-list">
                {history.map((item) => (
                  <div key={item.disc_hash} className="history-item">
                    <div className="history-main">
                      <div className="history-title-row">
                        <span className="job-drive">{item.drive || 'unknown drive'}</span>
                        <span className="job-title">{item.title || item.disc_label || 'Unknown title'}</span>
                        <span className="job-state" style={{ backgroundColor: item.media_type === 'tv' ? '#8b5cf6' : '#10b981' }}>
                          {item.media_type || 'movie'}
                        </span>
                      </div>
                      <div className="history-meta">
                        <span>Disc: {item.disc_label || 'n/a'}</span>
                        <span>Year: {item.year || 'n/a'}</span>
                        <span>Ripped: {item.ripped_at || 'n/a'}</span>
                      </div>
                      {item.output_path && <div className="history-path">{item.output_path}</div>}
                      {item.notes && <div className="history-notes">Notes: {item.notes}</div>}
                    </div>
                    <button
                      className="btn-secondary"
                      onClick={() =>
                        setHistoryEditModal({
                          disc_hash: item.disc_hash,
                          title: item.title || '',
                          year: item.year || '',
                          media_type: item.media_type || 'movie',
                          notes: item.notes || '',
                        })
                      }
                    >
                      Edit Metadata
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'accounts' && (
        <div className="content">
          <div className="grid-2">
            <div className="card">
              <h2>👤 Accounts</h2>
              {currentUser && (
                <p className="field-help">
                  Signed in as <strong>{currentUser.username}</strong>
                  {currentUser.is_admin ? ' (admin)' : ''}
                </p>
              )}
              <div className="history-list">
                {accounts.map((u) => (
                  <div key={u.id} className="history-item">
                    <div className="history-main">
                      <div className="history-title-row">
                        <span className="job-title">{u.username}</span>
                        <span className="job-state" style={{ backgroundColor: u.is_admin ? '#10b981' : '#6b7280' }}>
                          {u.is_admin ? 'admin' : 'user'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h2>➕ Create Account</h2>
              {currentUser?.is_admin ? (
                <>
                  <div className="form-group">
                    <label>Username</label>
                    <input
                      value={newAccountForm.username}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, username: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Password</label>
                    <input
                      type="password"
                      value={newAccountForm.password}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, password: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Role</label>
                    <select
                      value={newAccountForm.is_admin ? 'admin' : 'user'}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, is_admin: e.target.value === 'admin' })}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </div>
                  <button className="btn-primary" onClick={createAccount}>Create Account</button>
                </>
              ) : (
                <p className="empty-state">Only admin users can create accounts.</p>
              )}
            </div>
          </div>
        </div>
      )}

    {/* Manual Title Override Modal */}
    {overrideModal && (
      <div className="modal-overlay" onClick={() => setOverrideModal(null)}>
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>🔍 Search & Override Title</h2>
            <button className="modal-close" onClick={() => setOverrideModal(null)} title="Close manual override dialog">✕</button>
          </div>
          <div className="modal-body">
            <p className="modal-subtitle">Current: <strong>{overrideModal.jobTitle}</strong></p>
            
            <div className="form-group">
              <label>Search TMDB</label>
              <div className="search-input-row">
                <select value={searchMediaType} onChange={(e) => setSearchMediaType(e.target.value)}>
                  <option value="movie">Movie</option>
                  <option value="tv">TV Show</option>
                </select>
                <input
                  type="text"
                  placeholder="Search for title..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && searchQuery.trim()) {
                      searchTMDB(searchQuery.trim())
                    }
                  }}
                />
                <button
                  className="btn-primary"
                  onClick={() => searchQuery.trim() && searchTMDB(searchQuery.trim())}
                  disabled={searching}
                  title="Search TMDB for the current title query"
                >
                  {searching ? 'Searching...' : 'Search'}
                </button>
              </div>
            </div>

            {searchResults.length > 0 && (
              <div className="search-results">
                <h3>Results:</h3>
                {searchResults.map((result, idx) => (
                  <div key={idx} className="search-result-item">
                    <div className="result-info">
                      <span className="result-title">{result.title || result.name}</span>
                      <span className="result-year">{(result.release_date || result.first_air_date || '').substring(0, 4)}</span>
                    </div>
                    <button
                      className="btn-secondary"
                      onClick={() =>
                        overrideJobTitle(
                          overrideModal.jobId,
                          result.title || result.name,
                          (result.release_date || result.first_air_date || '').substring(0, 4),
                          searchMediaType
                        )
                      }
                      title="Apply this TMDB result to the job and move the output to the library"
                    >
                      Select
                    </button>
                  </div>
                ))}
              </div>
            )}

            {searchQuery && !searching && searchResults.length === 0 && (
              <p className="empty-state">No results found. Try a different search.</p>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn-secondary" onClick={() => setOverrideModal(null)}>Close</button>
          </div>
        </div>
      </div>
    )}

    {historyEditModal && (
      <div className="modal-overlay" onClick={() => setHistoryEditModal(null)}>
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>✏️ Edit Rip Metadata</h2>
            <button className="modal-close" onClick={() => setHistoryEditModal(null)}>✕</button>
          </div>

          <div className="modal-body">
            <div className="form-group">
              <label>Title</label>
              <input
                value={historyEditModal.title}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, title: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Year</label>
              <input
                value={historyEditModal.year}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, year: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Media Type</label>
              <select
                value={historyEditModal.media_type}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, media_type: e.target.value })}
              >
                <option value="movie">movie</option>
                <option value="tv">tv</option>
              </select>
            </div>
            <div className="form-group">
              <label>Notes</label>
              <input
                value={historyEditModal.notes}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, notes: e.target.value })}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn-secondary" onClick={() => setHistoryEditModal(null)}>Cancel</button>
            <button className="btn-primary" onClick={saveHistoryCorrection}>Save</button>
          </div>
        </div>
      </div>
    )}
  </div>
  )
}
