'use strict';

(function () {
	const API_BASE = window.OMNICONTROL_API || `${window.location.protocol}//${window.location.hostname}:8000`;

	const state = {
		devices: [],
		history: [],
		stats: { total: 0, online: 0, homekit: 0, legacy: 0 }
	};

	const COMMAND_PRESETS = [
		{ id: 'power_on', label: 'Power On' },
		{ id: 'power_off', label: 'Power Off' },
		{ id: 'power_toggle', label: 'Power Toggle' },
		{ id: 'volume_up', label: 'Volume +' },
		{ id: 'volume_down', label: 'Volume -' },
		{ id: 'channel_up', label: 'Channel +' },
		{ id: 'channel_down', label: 'Channel -' },
		{ id: 'nav_up', label: 'Navigate Up' },
		{ id: 'nav_down', label: 'Navigate Down' },
		{ id: 'nav_left', label: 'Navigate Left' },
		{ id: 'nav_right', label: 'Navigate Right' },
		{ id: 'nav_select', label: 'Select / OK' }
	];

	let pairingFormInitialized = false;

	document.addEventListener('DOMContentLoaded', init);

	async function init() {
		await bootstrap();
		renderQuickStats();
		renderDeviceList();
		initPairingForm();
		renderDeviceInsights();
		renderUpdateHistory();
		initDeviceFilter();
		initScanButton();
		await initSettingsForm();
		initUpdateForm();
	}

	async function bootstrap() {
		try {
			const [devicesRes, statsRes, historyRes] = await Promise.all([
				fetchJson(`${API_BASE}/api/devices`),
				fetchJson(`${API_BASE}/api/stats`),
				fetchJson(`${API_BASE}/api/updates/history`)
			]);
			state.devices = Array.isArray(devicesRes.devices) ? devicesRes.devices : [];
			state.history = Array.isArray(historyRes) ? historyRes : [];
			state.stats = statsRes || state.stats;
		} catch (error) {
			console.warn('Falling back to local seed data:', error);
			state.devices = getSeedDevices();
			state.history = getSeedHistory();
			state.stats = collectDeviceStats();
			showToast('Hub API unreachable. Showing local demo data.');
		}
	}

	function getSeedDevices() {
		return [
			{
				id: 'display-living-tv',
				name: 'LG OLED Gallery',
				type: 'Display',
				room: 'Living room',
				protocols: ['bluetooth'],
				integrations: ['scene'],
				status: 'online',
				last_seen: 'Boot',
				firmware: 'v1.2.3'
			},
			{
				id: 'monitor-home-office',
				name: 'Samsung Odyssey G7',
				type: 'Monitor',
				room: 'Home office',
				protocols: ['bluetooth'],
				integrations: ['presence'],
				status: 'online',
				last_seen: 'Boot',
				firmware: 'v1.1.0'
			},
			{
				id: 'light-homekit',
				name: 'Nanoleaf Canvas',
				type: 'Lighting',
				room: 'Studio',
				protocols: ['homekit'],
				integrations: ['scene'],
				status: 'online',
				last_seen: 'Boot',
				firmware: 'v5.4.1'
			}
		];
	}

	function getSeedHistory() {
		return [
			{
				version: '1.0.0',
				description: 'Initial public release – Bluetooth display control + dashboard.',
				date: '2025-09-12'
			},
			{
				version: '0.9.5-beta',
				description: 'Added HomeKit bridge discovery and IR recording helpers.',
				date: '2025-07-01'
			}
		];
	}

	function renderQuickStats() {
		const container = document.querySelector('[data-quick-stats]');
		if (!container) {
			return;
		}

		const { total, online, homekit, legacy } = collectDeviceStats();
		container.innerHTML = [
			'<h2>System Snapshot</h2>',
			'<div class="metrics">',
			`<div><strong>${total}</strong><span>total devices</span></div>`,
			`<div><strong>${online}</strong><span>online right now</span></div>`,
			`<div><strong>${homekit}</strong><span>HomeKit accessories</span></div>`,
			`<div><strong>${legacy}</strong><span>legacy IR ready</span></div>`,
			'</div>'
		].join('');
	}

	function renderDeviceList() {
		const list = document.querySelector('[data-device-list]');
		if (!list) {
			return;
		}

		const filterEl = document.querySelector('[data-device-filter]');
		const query = filterEl ? filterEl.value.trim().toLowerCase() : '';
		const filtered = state.devices.filter((device) => {
			if (!query) {
				return true;
			}
			const searchable = [
				device.name,
				device.room,
				device.type,
				(device.protocols || []).join(' '),
				(device.integrations || []).join(' ')
			]
				.join(' ')
				.toLowerCase();
			return searchable.includes(query);
		});

		if (!filtered.length) {
			list.innerHTML = '<p>No devices match your filters. Try another search or run a new scan.</p>';
			return;
		}

		list.innerHTML = filtered.map(toDeviceMarkup).join('');
		updatePairingOptions();
		list.querySelectorAll('[data-action]').forEach((button) => {
			button.addEventListener('click', handleDeviceAction);
		});
	}

	function renderDeviceInsights() {
		const container = document.querySelector('[data-device-insights]');
		if (!container) {
			return;
		}

		const metrics = container.querySelector('.metrics');
		if (!metrics) {
			return;
		}

		const stats = collectDeviceStats();
		metrics.innerHTML = [
			`<div><strong>${stats.online}</strong><span>online devices</span></div>`,
			`<div><strong>${stats.homekit}</strong><span>HomeKit accessories</span></div>`,
			`<div><strong>${stats.legacy}</strong><span>legacy IR profiles ready</span></div>`
		].join('');
	}

	function renderUpdateHistory() {
		const timeline = document.querySelector('[data-update-history]');
		if (!timeline) {
			return;
		}

		if (!state.history.length) {
			timeline.innerHTML = '<p>No update history yet.</p>';
			return;
		}

		timeline.innerHTML = state.history
			.slice()
			.sort((a, b) => b.date.localeCompare(a.date))
			.map((entry) => {
				return [
					'<div class="timeline-item">',
					`<div class="timeline-header"><strong>${escapeHtml(entry.version)}</strong><span class="timeline-meta">${escapeHtml(formatDate(entry.date))}</span></div>`,
					`<span>${escapeHtml(entry.description)}</span>`,
					'</div>'
				].join('');
			})
			.join('');
	}

	function initDeviceFilter() {
		const filterEl = document.querySelector('[data-device-filter]');
		if (!filterEl) {
			return;
		}
		filterEl.addEventListener('input', debounce(renderDeviceList, 150));
	}

	function initScanButton() {
		const button = document.querySelector('[data-device-discover]');
		if (!button) {
			return;
		}

		button.addEventListener('click', async () => {
			const original = button.textContent;
			button.textContent = 'Scanning...';
			button.disabled = true;
			try {
				const response = await fetchJson(`${API_BASE}/api/scan`, { method: 'POST' });
				const discovered = Array.isArray(response.discovered) ? response.discovered : [];
				const stats = response.stats || {};
				mergeDevices(discovered);
				if (stats.total !== undefined) {
					state.stats = stats;
				}
				renderQuickStats();
				renderDeviceInsights();
				renderDeviceList();
				if (discovered.length) {
					showToast(`${discovered.length} device(s) discovered.`);
					logActivity(`Scan found: ${discovered.map((item) => item.name).join(', ')}`);
				} else {
					showToast('Scan completed. No new devices found.');
				}
			} catch (error) {
				console.error('Scan failed:', error);
				showToast('Scan failed. Check the hub logs.');
			} finally {
				button.textContent = original;
				button.disabled = false;
			}
		});
	}

	function mergeDevices(newDevices) {
		if (!Array.isArray(newDevices)) {
			return;
		}
		const reference = new Map(state.devices.map((device) => [device.id, device]));
		newDevices.forEach((device) => {
			if (!device || !device.id) {
				return;
			}
			reference.set(device.id, device);
		});
		state.devices = Array.from(reference.values());
		updatePairingOptions();
	}

	function initPairingForm() {
		const form = document.querySelector('[data-pair-form]');
		if (!form) {
			return;
		}
		if (pairingFormInitialized) {
			updatePairingOptions();
			return;
		}
		pairingFormInitialized = true;
		const feedback = form.querySelector('[data-pair-feedback]');
		const addressInput = form.querySelector('[data-pair-address]');
		if (addressInput) {
			addressInput.addEventListener('change', handlePairAddressChange);
			addressInput.addEventListener('input', handlePairAddressChange);
		}

		form.addEventListener('submit', async (event) => {
			event.preventDefault();
			const submitButton = form.querySelector('[type="submit"]');
			const originalText = submitButton ? submitButton.textContent : '';
			if (submitButton) {
				submitButton.disabled = true;
				submitButton.textContent = 'Pairing...';
			}
			if (feedback) {
				feedback.textContent = '';
				feedback.classList.remove('success');
			}

			try {
				const payload = collectPairingPayload(form);
				const device = await fetchJson(`${API_BASE}/api/pairings`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				});
				mergeDevices([device]);
				renderQuickStats();
				renderDeviceInsights();
				renderDeviceList();
				showToast(`${device.name || 'Device'} paired successfully.`);
				if (feedback) {
					feedback.textContent = 'Pairing saved to the hub.';
					feedback.classList.add('success');
				}
				if (form.elements.deviceId) {
					form.elements.deviceId.value = device.id;
				}
			} catch (error) {
				console.error('Pairing failed:', error);
				const message = error && error.message ? error.message : 'Pairing failed. Check inputs and hub logs.';
				if (feedback) {
					feedback.textContent = message;
					feedback.classList.remove('success');
				}
				showToast('Pairing failed. Check the hub logs.');
			} finally {
				if (submitButton) {
					submitButton.disabled = false;
					submitButton.textContent = originalText;
				}
			}
		});

		updatePairingOptions();
	}

	function handlePairAddressChange(event) {
		const input = event.currentTarget;
		const form = input.closest('form');
		if (!form) {
			return;
		}
		const value = input.value.trim().toUpperCase();
		const match = state.devices.find((device) => (device.address || '').toUpperCase() === value);
		const deviceIdField = form.elements.deviceId;
		if (match && deviceIdField) {
			deviceIdField.value = match.id;
		} else if (deviceIdField) {
			deviceIdField.value = '';
		}
		if (match) {
			if (form.elements.name && !form.elements.name.value) {
				form.elements.name.value = match.name || '';
			}
			if (form.elements.room && !form.elements.room.value) {
				form.elements.room.value = match.room || '';
			}
			if (form.elements.type && !form.elements.type.value) {
				form.elements.type.value = match.type || 'Display';
			}
		}
	}

	function collectPairingPayload(form) {
		const address = form.elements.address ? form.elements.address.value.trim() : '';
		if (!address) {
			throw new Error('Enter the Bluetooth device address.');
		}
		const payload = {
			address,
			name: form.elements.name ? form.elements.name.value.trim() : undefined,
			room: form.elements.room ? form.elements.room.value.trim() : undefined,
			type: form.elements.type ? form.elements.type.value.trim() : undefined,
			commands: []
		};
		if (form.elements.deviceId && form.elements.deviceId.value.trim()) {
			payload.device_id = form.elements.deviceId.value.trim();
		}

		COMMAND_PRESETS.forEach((preset) => {
			const charField = form.elements[`command-${preset.id}-char`];
			const payloadField = form.elements[`command-${preset.id}-payload`];
			const ackField = form.elements[`command-${preset.id}-ack`];
			const characteristic = charField ? charField.value.trim() : '';
			const rawPayload = payloadField ? payloadField.value.trim() : '';
			const withResponse = ackField ? ackField.checked : false;
			if (!characteristic && !rawPayload) {
				return;
			}
			if (!characteristic) {
				throw new Error(`${preset.label}: add the characteristic UUID.`);
			}
			const command = {
				id: preset.id,
				label: preset.label,
				characteristic
			};
			if (rawPayload) {
				const cleaned = rawPayload.replace(/0x/gi, '').replace(/[^0-9a-fA-F]/g, '');
				if (!cleaned) {
					throw new Error(`${preset.label}: payload must be hex (0-9, A-F).`);
				}
				if (cleaned.length % 2 !== 0) {
					throw new Error(`${preset.label}: hex payload must have an even number of characters.`);
				}
				command.payload_hex = cleaned;
			}
			if (withResponse) {
				command.with_response = true;
			}
			payload.commands.push(command);
		});

		if (!payload.name) {
			delete payload.name;
		}
		if (!payload.room) {
			delete payload.room;
		}
		if (!payload.type) {
			payload.type = 'Display';
		}

		return payload;
	}

	function updatePairingOptions() {
		const datalist = document.querySelector('[data-pair-addresses]');
		if (!datalist) {
			return;
		}
		datalist.innerHTML = '';
		const seen = new Set();
		state.devices
			.filter((device) => Array.isArray(device.protocols) && device.protocols.includes('bluetooth') && device.address)
			.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
			.forEach((device) => {
				const address = device.address;
				if (!address || seen.has(address)) {
					return;
				}
				seen.add(address);
				const option = document.createElement('option');
				option.value = address;
				option.label = `${device.name || address} (${address})`;
				datalist.appendChild(option);
			});
	}

	function prefillPairingForm(deviceId) {
		const form = document.querySelector('[data-pair-form]');
		if (!form) {
			return;
		}
		const device = state.devices.find((entry) => entry.id === deviceId);
		if (!device) {
			return;
		}
		form.reset();
		if (form.elements.address) {
			form.elements.address.value = device.address || '';
		}
		if (form.elements.name) {
			form.elements.name.value = device.name || '';
		}
		if (form.elements.room) {
			form.elements.room.value = device.room || '';
		}
		if (form.elements.type) {
			form.elements.type.value = device.type || 'Display';
		}
		if (form.elements.deviceId) {
			form.elements.deviceId.value = device.id;
		}
		const metadata = device.metadata || {};
		const commands = Array.isArray(metadata.ble_commands) ? metadata.ble_commands : [];
		COMMAND_PRESETS.forEach((preset) => {
			const existing = commands.find((command) => command.id === preset.id);
			const charField = form.elements[`command-${preset.id}-char`];
			const payloadField = form.elements[`command-${preset.id}-payload`];
			const ackField = form.elements[`command-${preset.id}-ack`];
			if (!existing) {
				if (charField) {
					charField.value = '';
				}
				if (payloadField) {
					payloadField.value = '';
				}
				if (ackField) {
					ackField.checked = false;
				}
				return;
			}
			if (charField) {
				charField.value = existing.characteristic || '';
			}
			if (payloadField) {
				payloadField.value = existing.payload_hex || '';
			}
			if (ackField) {
				ackField.checked = Boolean(existing.with_response);
			}
		});
		form.scrollIntoView({ behavior: 'smooth', block: 'center' });
		showToast(`Prefilled controls for ${device.name || device.id}.`);
	}

	async function initSettingsForm() {
		const form = document.querySelector('[data-settings-form]');
		if (!form) {
			return;
		}
		const feedback = form.querySelector('[data-settings-feedback]');

		try {
			const remote = await fetchJson(`${API_BASE}/api/settings`);
			hydrateSettings(form, remote);
		} catch (error) {
			console.warn('Unable to load settings. Using defaults.', error);
		}

		form.addEventListener('submit', async (event) => {
			event.preventDefault();
			const formData = new FormData(form);
			const payload = Object.fromEntries(formData.entries());
			payload.autoUpdate = formData.has('autoUpdate');
			payload.remoteAccess = formData.has('remoteAccess');

			try {
				await fetchJson(`${API_BASE}/api/settings`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				});
				if (feedback) {
					feedback.textContent = 'Preferences synced with the hub.';
					feedback.classList.add('success');
				}
				logActivity('Settings synced with Raspberry Pi hub.');
			} catch (error) {
				if (feedback) {
					feedback.textContent = 'Unable to sync settings. Changes are unsaved.';
					feedback.classList.remove('success');
				}
				console.error('Settings sync failed:', error);
			}
		});
	}

	function hydrateSettings(form, settings) {
		if (!settings) {
			return;
		}
		Object.entries(settings).forEach(([key, value]) => {
			const element = form.elements.namedItem(key);
			if (!element) {
				return;
			}
			if (element.type === 'checkbox') {
				element.checked = Boolean(value);
				return;
			}
			element.value = value;
		});
	}

	function initUpdateForm() {
		const form = document.querySelector('[data-update-form]');
		if (!form) {
			return;
		}
		const feedback = form.querySelector('[data-update-feedback]');

		form.addEventListener('submit', async (event) => {
			event.preventDefault();
			const formData = new FormData(form);
			const file = formData.get('firmware');
			if (!file || !file.name) {
				if (feedback) {
					feedback.textContent = 'Select a firmware package before staging an update.';
					feedback.classList.remove('success');
				}
				return;
			}

			try {
				const response = await fetchJson(`${API_BASE}/api/updates`, {
					method: 'POST',
					body: formData
				});
				const entry = response.entry || {
					version: deriveVersionFromFilename(file.name),
					description: `Staged ${file.name}`,
					date: new Date().toISOString().split('T')[0]
				};
				if (Array.isArray(response.history)) {
					state.history = response.history;
				} else {
					state.history.push(entry);
				}
				renderUpdateHistory();
				if (feedback) {
					feedback.textContent = `${file.name} staged successfully.`;
					feedback.classList.add('success');
				}
				logActivity(`Firmware package ${file.name} staged on hub.`);
				form.reset();
			} catch (error) {
				if (feedback) {
					feedback.textContent = 'Firmware staging failed. Check hub logs.';
					feedback.classList.remove('success');
				}
				console.error('Update staging failed:', error);
			}
		});
	}

	function collectDeviceStats() {
		if (state.devices.length) {
			const total = state.devices.length;
			const online = state.devices.filter((device) => device.status === 'online').length;
			const homekit = state.devices.filter((device) => (device.protocols || []).includes('homekit')).length;
			const legacy = state.devices.filter((device) => (device.protocols || []).includes('ir')).length;
			state.stats = { total, online, homekit, legacy };
		}
		return state.stats;
	}

	async function handleDeviceAction(event) {
		const button = event.currentTarget;
		const id = button.getAttribute('data-device-id');
		const action = button.getAttribute('data-action');
		if (!id || !action) {
			return;
		}

		try {
			if (action === 'prefill-pair') {
				prefillPairingForm(id);
				return;
			}

			if (action === 'toggle') {
				const updated = await fetchJson(`${API_BASE}/api/devices/${id}/toggle`, { method: 'POST' });
				mergeDevices([updated]);
				renderQuickStats();
				renderDeviceInsights();
				renderDeviceList();
				logActivity(`${updated.name} toggled ${updated.status}.`);
				return;
			}

			if (action === 'ping') {
				await fetchJson(`${API_BASE}/api/devices/${id}/ping`, { method: 'POST' });
				showToast('Ping sent.');
				logActivity(`Pinged ${id}.`);
			}

			if (action === 'command') {
				const commandId = button.getAttribute('data-command-id');
				if (!commandId) {
					return;
				}
				const updated = await fetchJson(`${API_BASE}/api/devices/${id}/command`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ command: commandId })
				});
				mergeDevices([updated]);
				renderQuickStats();
				renderDeviceInsights();
				renderDeviceList();
				showToast(`${updated.name} command sent (${formatCommandLabel(commandId)}).`);
				logActivity(`Sent ${formatCommandLabel(commandId)} to ${updated.name}.`);
				return;
			}
		} catch (error) {
			console.error('Device action failed:', error);
			showToast('Device action failed.');
		}
	}

	function toDeviceMarkup(device) {
		const protocols = (device.protocols || []).map(formatProtocol).join(', ');
		const integrations = (device.integrations || []).join(', ');
		const statusClass = device.status === 'online' ? 'status-online' : 'status-offline';
		const statusLabel = device.status === 'online' ? 'Online' : 'Offline';
		const metadata = device.metadata || {};
		const extras = [];
		if (metadata.is_on !== undefined) {
			extras.push(`Power ${metadata.is_on ? 'On' : 'Off'}`);
		}
		if (metadata.rssi !== undefined && metadata.rssi !== null) {
			extras.push(`RSSI ${metadata.rssi} dBm`);
		}
		if (metadata.last_command && metadata.last_command.id) {
			extras.push(`Last command: ${formatCommandLabel(metadata.last_command.id)}`);
		}
		const commands = Array.isArray(metadata.ble_commands)
			? metadata.ble_commands.filter((entry) => entry && entry.id)
			: [];
		const needsPairing = (device.protocols || []).includes('bluetooth') && !commands.length;
		const commandMarkup = commands.length
			? `<div class="device-commands">${commands
					.map((command) => {
						const commandLabel = escapeHtml(command.label || formatCommandLabel(command.id));
						return `<button class="btn tertiary small" data-device-id="${escapeHtml(device.id)}" data-action="command" data-command-id="${escapeHtml(command.id)}">${commandLabel}</button>`;
					})
					.join('')}</div>`
			: '';
		const pairingButton = needsPairing
			? `<button class="btn small tertiary" data-device-id="${escapeHtml(device.id)}" data-action="prefill-pair">Map controls</button>`
			: '';

		return [
			'<article class="device">',
			`<h3>${escapeHtml(device.name)}</h3>`,
			`<div class="status-pill ${statusClass}">${statusLabel}</div>`,
			'<div class="device-meta">',
			`<span>${escapeHtml(device.type)}</span>`,
			`<span>${escapeHtml(device.room || 'Unassigned')}</span>`,
			`<span>${escapeHtml(protocols || 'Unknown')}</span>`,
			'</div>',
			`<p class="section-subtitle">Last seen: ${escapeHtml(device.last_seen || 'Unknown')}</p>`,
			`<p class="section-subtitle">Integrations: ${escapeHtml(integrations || 'Pending setup')}</p>`,
			extras.length ? `<p class="section-subtitle">${escapeHtml(extras.join(' | '))}</p>` : '',
			commandMarkup,
			'<div class="device-actions">',
			`<button class="btn small" data-device-id="${escapeHtml(device.id)}" data-action="toggle">Toggle power</button>`,
			`<button class="btn small secondary" data-device-id="${escapeHtml(device.id)}" data-action="ping">Ping</button>`,
			pairingButton,
			'</div>',
			'</article>'
		].join('');
	}

	function formatProtocol(protocol) {
		switch (protocol) {
			case 'bluetooth':
				return 'Bluetooth LE';
			case 'homekit':
				return 'Apple HomeKit';
			case 'ir':
				return 'Infrared (IR)';
			default:
				return protocol;
		}
	}

	function formatCommandLabel(commandId) {
		if (!commandId) {
			return 'Command';
		}
		return commandId
			.replace(/[-_]/g, ' ')
			.split(' ')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	function logActivity(message) {
		const container = document.querySelector('[data-activity-log]');
		if (!container) {
			return;
		}

		container.insertAdjacentHTML(
			'afterbegin',
			[
				'<div class="timeline-item">',
				`<strong>${escapeHtml(new Date().toLocaleTimeString())}</strong>`,
				`<span>${escapeHtml(message)}</span>`,
				'</div>'
			].join('')
		);
	}

	function showToast(message) {
		if (!message) {
			return;
		}

		const toast = document.createElement('div');
		toast.textContent = message;
		toast.style.position = 'fixed';
		toast.style.bottom = '32px';
		toast.style.right = '32px';
		toast.style.padding = '0.9rem 1.2rem';
		toast.style.background = 'rgba(15, 23, 42, 0.92)';
		toast.style.color = '#ffffff';
		toast.style.borderRadius = '12px';
		toast.style.boxShadow = '0 12px 30px rgba(15, 23, 42, 0.25)';
		toast.style.zIndex = '1000';
		toast.style.fontSize = '0.9rem';
		toast.style.opacity = '0';
		toast.style.transition = 'opacity 0.3s ease';

		document.body.appendChild(toast);
		requestAnimationFrame(() => {
			toast.style.opacity = '1';
		});

		setTimeout(() => {
			toast.style.opacity = '0';
			toast.addEventListener(
				'transitionend',
				() => {
					toast.remove();
				},
				{ once: true }
			);
		}, 2600);
	}

	async function fetchJson(url, options) {
		const response = await fetch(url, options);
		const contentType = response.headers.get('content-type') || '';
		const expectsJson = contentType.includes('application/json');
		let payload;
		if (expectsJson) {
			try {
				payload = await response.json();
			} catch (error) {
				payload = null;
			}
		} else {
			try {
				payload = await response.text();
			} catch (error) {
				payload = '';
			}
		}

		if (!response.ok) {
			let message = `${response.status} ${response.statusText}`;
			if (payload) {
				if (typeof payload === 'string') {
					message = payload;
				} else if (payload.detail) {
					message = payload.detail;
				} else {
					message = JSON.stringify(payload);
				}
			}
			throw new Error(message);
		}

		return payload;
	}

	function debounce(fn, wait) {
		let timeout;
		return function (...args) {
			clearTimeout(timeout);
			timeout = setTimeout(() => fn.apply(this, args), wait);
		};
	}

	function escapeHtml(value) {
		return String(value)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}

	function deriveVersionFromFilename(filename) {
		const match = filename.match(/(\d+\.\d+(?:\.\d+)?)/);
		return match ? `v${match[1]}` : 'Unversioned build';
	}

	function formatDate(dateString) {
		const date = new Date(dateString);
		if (Number.isNaN(date.getTime())) {
			return dateString;
		}
		return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}
})();
