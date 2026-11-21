/* gallery page script (ADR-0009) */

        let isMobile = window.innerWidth <= 768;
        let zoomLevel = 1;
        let maxZoom = 4;
        let userPreferences = {};

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        // 获取 CSRF Token（从模板变量或cookie）
        function getCsrfToken() {
            // 优先使用模板变量
            if (window.csrfToken) return window.csrfToken;
            // 回退到cookie
            const match = document.cookie.match(/csrf_token=([^;]+)/);
            return match ? match[1] : '';
        }

        // 从服务器传入的初始设置（由 Jinja2 模板渲染时传入）

        document.addEventListener('DOMContentLoaded', function() {
            // 首先声明所有 DOM 元素变量
            const settingsBtn = document.getElementById('settingsBtn');
            const sidebarOverlay = document.getElementById('sidebarOverlay');
            const sidebar = document.getElementById('sidebar');
            const sidebarClose = document.getElementById('sidebarClose');

            // 保存用户偏好设置
            function saveUserPreferences(preferences) {
                const data = { preferences: preferences };

                fetch('/gallery/api/preferences', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': getCsrfToken()
                    },
                    body: JSON.stringify(data)
                })
                .then(response => response.json())
                .then(result => {
                    if (!result.success) {
                        console.error('保存用户偏好设置失败:', result.message);
                        // 保存失败时回退到 localStorage
                        saveToLocalSettings();
                    }
                })
                .catch(error => {
                    console.error('保存用户偏好设置失败:', error);
                    // 保存失败时回退到 localStorage
                    saveToLocalSettings();
                });
            }

            // 批量保存设置到服务器
            function updateAndSavePreferences(updates) {
                // 键名映射：API 格式 -> localStorage 格式
                const keyMapping = {
                    'discover_enabled': 'discoverEnabled',
                    'discover_format': 'discoverFormat',
                    'discover_rounded': 'discoverRounded',
                    'discover_shape': 'discoverShape',
                    'discover_size': 'discoverSize',
                    'sidebar_transparency': 'sidebarTransparent'
                };

                // 更新本地存储
                Object.keys(updates).forEach(key => {
                    const localKey = keyMapping[key] || key;
                    if (typeof updates[key] === 'object') {
                        localStorage.setItem(localKey, JSON.stringify(updates[key]));
                    } else {
                        localStorage.setItem(localKey, updates[key]);
                    }
                });

                // 合并到 userPreferences
                Object.assign(userPreferences, updates);

                // 保存到服务器
                saveUserPreferences(userPreferences);
            }
            // 定义应用用户偏好设置到界面的函数
            function applyUserPreferences(preferences, deviceSpecific) {
                const discoverToggle = document.getElementById('discoverToggle');
                const discoverSection = document.querySelector('.discover-section');
                const discoverFormatSetting = document.getElementById('discoverFormatSetting');
                const discoverRoundedSetting = document.getElementById('discoverRoundedSetting');
                const discoverSizeSetting = document.getElementById('discoverSizeSetting');
                const discoverFormatSelect = document.getElementById('discoverFormatSelect');
                const discoverRoundedToggle = document.getElementById('discoverRoundedToggle');
                const discoverShapeSelect = document.getElementById('discoverShapeSelect');
                const discoverSizeRange = document.getElementById('discoverSizeRange');
                const discoverSizeInput = document.getElementById('discoverSizeInput');
                const discoverWidthRange = document.getElementById('discoverWidthRange');
                const discoverWidthInput = document.getElementById('discoverWidthInput');
                const discoverHeightRange = document.getElementById('discoverHeightRange');
                const discoverHeightInput = document.getElementById('discoverHeightInput');

                // 应用发现功能开关（偏好缺失时回退 localStorage，确保区块仍能加载显示）
                if (discoverToggle) {
                    const enabled = ('discover_enabled' in preferences)
                        ? !!preferences.discover_enabled
                        : (localStorage.getItem('discoverEnabled') === null
                            ? true
                            : localStorage.getItem('discoverEnabled') === 'true');
                    discoverToggle.checked = enabled;
                    localStorage.setItem('discoverEnabled', enabled);

                    // 更新发现区域显示状态（区块在图片渲染完成后才显示，
                    // 避免"加载中"→网格 以及列数/尺寸变化造成的布局跳动）
                    if (enabled) {
                        discoverFormatSetting.classList.remove('disabled');
                        discoverRoundedSetting.classList.remove('disabled');
                        discoverSizeSetting.classList.remove('disabled');
                        // loadRandomImages 内部先应用最终布局参数再一次性渲染并显示区块
                        loadRandomImages();
                    } else {
                        discoverSection.classList.remove('visible');
                        discoverFormatSetting.classList.add('disabled');
                        discoverRoundedSetting.classList.add('disabled');
                        discoverSizeSetting.classList.add('disabled');
                    }
                }

                // 应用发现格式（仅移动端）
                if ('discover_format' in preferences && isMobile && discoverFormatSelect) {
                    discoverFormatSelect.value = preferences.discover_format;
                    localStorage.setItem('discoverFormat', preferences.discover_format);
                    if (preferences.discover_enabled) {
                        applyDiscoverFormat(preferences.discover_format);
                    }
                }

                // 应用发现图片圆角（仅移动端）
                if ('discover_rounded' in preferences && isMobile && discoverRoundedToggle) {
                    discoverRoundedToggle.checked = preferences.discover_rounded;
                    localStorage.setItem('discoverRounded', preferences.discover_rounded);
                    if (preferences.discover_enabled) {
                        applyDiscoverRounded();
                    }
                }

                // 应用发现图片形状（仅电脑端）
                if ('discover_shape' in preferences && !isMobile && discoverShapeSelect) {
                    discoverShapeSelect.value = preferences.discover_shape;
                    localStorage.setItem('discoverShape', preferences.discover_shape);

                    // 更新大小设置显示
                    const discoverSizeSquare = document.getElementById('discoverSizeSquare');
                    const discoverSizeRectangle = document.getElementById('discoverSizeRectangle');
                    if (preferences.discover_shape === 'rectangle') {
                        discoverSizeSquare.style.display = 'none';
                        discoverSizeRectangle.style.display = 'block';
                    } else {
                        discoverSizeSquare.style.display = 'block';
                        discoverSizeRectangle.style.display = 'none';
                    }
                    if (preferences.discover_enabled) {
                        applyDiscoverSize();
                    }
                }

                // 应用发现图片大小（仅电脑端）
                if ('discover_size' in preferences && !isMobile) {
                    const size = preferences.discover_size || { width: 150, height: 150 };
                    localStorage.setItem('discoverSize', JSON.stringify(size));

                    // 更新输入框和滑块的值
                    if (size.width) {
                        discoverSizeInput.value = size.width;
                        discoverSizeRange.value = size.width;
                    }
                    if (size.height) {
                        discoverHeightInput.value = size.height;
                        discoverHeightRange.value = size.height;
                    }
                    if (size.width && size.height) {
                        discoverWidthInput.value = size.width;
                        discoverWidthRange.value = size.width;
                    }
                    if (preferences.discover_enabled) {
                        applyDiscoverSize();
                    }
                }

                // 应用侧边栏透明度
                if ('sidebar_transparency' in preferences) {
                    const sidebarTransparentSelect = document.getElementById('sidebarTransparentSelect');
                    if (sidebarTransparentSelect) {
                        sidebarTransparentSelect.value = preferences.sidebar_transparency;
                        localStorage.setItem('sidebarTransparent', preferences.sidebar_transparency);
                        updateSidebarTransparency(preferences.sidebar_transparency);
                    }
                }
            }

            // 从 localStorage 加载旧设置（API 失败时使用）
            function loadLocalSettings() {
                const storedValue = localStorage.getItem('discoverEnabled');
                const discoverEnabled = storedValue === null ? true : storedValue === 'true';
                const discoverToggle = document.getElementById('discoverToggle');
                if (discoverToggle) {
                    discoverToggle.checked = discoverEnabled;
                }
                // 兜底：偏好接口失败时，仍按本地开关加载并显示发现区（渲染完成后显示）
                if (discoverEnabled) {
                    loadRandomImages();
                }
            }

            // 保存到 localStorage（API 失败时使用）
            function saveToLocalSettings() {
                // 设置已在各个事件监听器中保存到 localStorage
            }

            // 定义加载用户偏好设置函数
            function loadUserPreferences() {
                // 优先使用服务器传入的设置
                if (serverPreferences && Object.keys(serverPreferences).length > 0) {
                    userPreferences = serverPreferences;
                    applyUserPreferences(serverPreferences, serverDeviceSpecific || {});
                } else {
                    // 如果服务器没有传入设置，调用 API 获取
                    const deviceType = isMobile ? 'mobile' : 'desktop';
                    fetch(`/gallery/api/preferences?device=${deviceType}`)
                        .then(response => response.json())
                        .then(data => {
                            if (data.preferences) {
                                userPreferences = data.preferences;
                                applyUserPreferences(data.preferences, data.device_specific || []);
                            }
                        })
                        .catch(error => {
                            console.error('加载用户偏好设置失败:', error);
                            // 失败时使用 localStorage 中的旧设置
                            loadLocalSettings();
                        });
                }
            }

            // 加载用户偏好设置（多端同步）
            loadUserPreferences();

            // 移动端滚动隐藏/显示搜索栏
            let lastScrollY = 0;
            let controls = document.querySelector('.controls');
            let header = document.querySelector('.header');
            let scrollTimeout;

            if (isMobile) {
                window.addEventListener('scroll', function() {
                    const currentScrollY = window.scrollY;

                    // 只有当滚动距离超过一定阈值时才触发
                    if (Math.abs(currentScrollY - lastScrollY) > 10) {
                        if (currentScrollY > lastScrollY && currentScrollY > 50) {
                            // 向下滚动，隐藏搜索栏和标题
                            controls.classList.add('hidden');
                            header.classList.add('hidden');
                        } else {
                            // 向上滚动，显示搜索栏和标题
                            controls.classList.remove('hidden');
                            header.classList.remove('hidden');
                        }
                        lastScrollY = currentScrollY;
                    }

                    // 添加滚动结束检测
                    clearTimeout(scrollTimeout);
                    scrollTimeout = setTimeout(() => {
                    }, 100);
                }, { passive: true });
            }

            const galleryItems = document.querySelectorAll('.gallery-item');

            galleryItems.forEach(item => {
                item.addEventListener('click', function() {
                    const type = this.dataset.type;
                    if (type === 'folder') {
                        const path = this.dataset.path;
                        window.location.href = `/gallery/${encodeURIComponent(path)}`;
                    } else if (type === 'image') {
                        const url = this.dataset.url;
                        openLightbox(url);
                    }
                });
            });

            const searchBox = document.getElementById('searchBox');
            const searchBtn = document.getElementById('searchBtn');

            function performSearch() {
                const query = searchBox.value.trim();
                if (!query) {
                    location.reload();
                    return;
                }

                searchBtn.textContent = '搜索中...';
                searchBtn.disabled = true;

                fetch(`/gallery/api/search?q=${encodeURIComponent(query)}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data.results) {
                            displaySearchResults(data.results, query);
                        }
                        searchBtn.textContent = '搜索';
                        searchBtn.disabled = false;
                    })
                    .catch(error => {
                        console.error('搜索失败:', error);
                        searchBtn.textContent = '搜索';
                        searchBtn.disabled = false;
                    });
            }

            function displaySearchResults(results, query) {
                const gallery = document.getElementById('gallery');
                gallery.innerHTML = '';

                const title = document.createElement('div');
                title.style.gridColumn = '1 / -1';
                title.style.padding = '20px';
                title.style.textAlign = 'center';
                title.style.color = '#2c3e50';
                const h2 = document.createElement('h2');
                h2.textContent = `搜索结果: "${query}"`;
                const p = document.createElement('p');
                p.textContent = `找到 ${results.folders.length} 个文件夹，${results.images.length} 张图片`;
                title.appendChild(h2);
                title.appendChild(p);
                gallery.appendChild(title);

                results.folders.forEach(folder => {
                    const item = document.createElement('div');
                    item.className = 'gallery-item gallery-folder';
                    item.dataset.type = 'folder';
                    item.dataset.path = folder.path;

                    if (folder.cover) {
                        item.innerHTML = `
                            <div class="image-container">
                                <img src="${escapeHtml(folder.cover)}" alt="${escapeHtml(folder.name)}" class="gallery-image folder-thumbnail" loading="lazy">
                                <div class="folder-overlay">
                                    <div class="folder-name">${escapeHtml(folder.name)}</div>
                                    <div class="folder-count">${escapeHtml(String(folder.count))} 张图片</div>
                                </div>
                            </div>
                        `;
                    } else {
                        item.innerHTML = `
                            <div class="image-container">
                                <div class="folder-icon">
                                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#667eea">
                                        <path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
                                    </svg>
                                </div>
                                <div class="folder-overlay">
                                    <div class="folder-name">${escapeHtml(folder.name)}</div>
                                    <div class="folder-count">${escapeHtml(String(folder.count))} 张图片</div>
                                </div>
                            </div>
                        `;
                    }

                    item.addEventListener('click', function() {
                        const path = this.dataset.path;
                        window.location.href = `/gallery/${encodeURIComponent(path)}`;
                    });

                    gallery.appendChild(item);
                });

                results.images.forEach(image => {
                    const item = document.createElement('div');
                    item.className = 'gallery-item';
                    item.dataset.type = 'image';
                    item.dataset.url = image.url;

                    item.innerHTML = `
                        <div class="image-container">
                            <img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.name)}" class="gallery-image" loading="lazy">
                        </div>
                    `;

                    item.addEventListener('click', function() {
                        openLightbox(image.url);
                    });

                    gallery.appendChild(item);
                });

                if (results.folders.length === 0 && results.images.length === 0) {
                    const noResults = document.createElement('div');
                    noResults.className = 'no-images';
                    noResults.textContent = '未找到匹配的结果';
                    gallery.appendChild(noResults);
                }

                // 为搜索结果中的缩略图绑定加载淡入
                bindThumbnailFade();
            }

            searchBtn.addEventListener('click', performSearch);
            searchBox.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    performSearch();
                }
            });

            document.getElementById('lightboxClose').addEventListener('click', closeLightbox);
            document.getElementById('lightboxPrev').addEventListener('click', showPrevDiscoveryImage);
            document.getElementById('lightboxNext').addEventListener('click', showNextDiscoveryImage);
            document.getElementById('lightbox').addEventListener('click', function(e) {
                if (e.target === this) {
                    closeLightbox();
                }
            });

            // 添加滚轮缩放功能
            document.getElementById('lightboxImage').addEventListener('wheel', function(e) {
                if (!document.getElementById('lightbox').classList.contains('active')) return;
                
                e.preventDefault();
                
                if (e.deltaY < 0) {
                    // 向上滚动，放大
                    zoomIn();
                } else {
                    // 向下滚动，缩小
                    zoomOut();
                }
            });

            document.addEventListener('keydown', function(e) {
                if (!document.getElementById('lightbox').classList.contains('active')) return;
                if (e.key === 'Escape') closeLightbox();
                if (e.key === 'ArrowLeft') showPrevDiscoveryImage();
                if (e.key === 'ArrowRight') showNextDiscoveryImage();
            });

            settingsBtn.addEventListener('click', function() {
                sidebarOverlay.classList.add('active');
                sidebar.classList.add('active');
            });

            function closeSidebar() {
                sidebarOverlay.classList.remove('active');
                sidebar.classList.remove('active');
            }

            sidebarClose.addEventListener('click', closeSidebar);
            sidebarOverlay.addEventListener('click', closeSidebar);

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && sidebar.classList.contains('active')) {
                    closeSidebar();
                }
            });

            // 定义发现相关的辅助函数
            function applyDiscoverFormat(format) {
                const discoverGallery = document.getElementById('discoverGallery');
                if (isMobile) {
                    if (format === 'one') {
                        discoverGallery.style.gridTemplateColumns = 'repeat(1, 1fr)';
                    } else if (format === 'three') {
                        discoverGallery.style.gridTemplateColumns = 'repeat(3, 1fr)';
                    } else {
                        discoverGallery.style.gridTemplateColumns = 'repeat(2, 1fr)';
                    }
                }
            }

            function applyDiscoverRounded() {
                const discoverGallery = document.getElementById('discoverGallery');
                const discoverRoundedToggle = document.getElementById('discoverRoundedToggle');

                if (!discoverGallery || !discoverRoundedToggle) return;

                const isEnabled = discoverRoundedToggle.checked;

                if (isMobile) {
                    if (isEnabled) {
                        discoverGallery.classList.add('rounded');
                        discoverGallery.classList.remove('no-rounded');
                        discoverGallery.style.gap = '8px';
                        discoverGallery.style.padding = '0 10px';
                    } else {
                        discoverGallery.classList.remove('rounded');
                        discoverGallery.classList.add('no-rounded');
                        discoverGallery.style.gap = '0';
                        discoverGallery.style.padding = '0';
                    }
                }
            }

            function applyDiscoverSize() {
                const discoverGallery = document.getElementById('discoverGallery');
                const discoverToggle = document.getElementById('discoverToggle');
                const discoverShapeSelect = document.getElementById('discoverShapeSelect');
                const discoverSizeInput = document.getElementById('discoverSizeInput');
                const discoverWidthInput = document.getElementById('discoverWidthInput');
                const discoverHeightInput = document.getElementById('discoverHeightInput');

                if (!discoverGallery || !discoverToggle || !discoverShapeSelect) return;

                const isEnabled = discoverToggle.checked;
                const currentShape = discoverShapeSelect.value;
                let width, height;

                if (currentShape === 'rectangle') {
                    width = discoverWidthInput ? parseInt(discoverWidthInput.value) : 200;
                    height = discoverHeightInput ? parseInt(discoverHeightInput.value) : 150;
                } else {
                    width = discoverSizeInput ? parseInt(discoverSizeInput.value) : 150;
                    height = width;
                }

                const items = discoverGallery.querySelectorAll('.discover-item');

                if (!isMobile && isEnabled) {
                    const gap = 20;
                    discoverGallery.style.gap = `${gap}px`;
                    discoverGallery.style.gridTemplateColumns = `repeat(auto-fill, minmax(${width}px, 1fr))`;

                    items.forEach(item => {
                        item.style.aspectRatio = 'unset';
                        item.style.width = `${width}px`;
                        item.style.height = `${height}px`;
                        item.style.display = 'flex';
                        item.style.alignItems = 'center';
                        item.style.justifyContent = 'center';

                        const img = item.querySelector('img');
                        if (img) {
                            img.style.width = '100%';
                            img.style.height = '100%';
                            img.style.objectFit = 'cover';
                        }
                    });
                } else {
                    discoverGallery.style.gap = '';
                    discoverGallery.style.gridTemplateColumns = '';

                    items.forEach(item => {
                        item.style.aspectRatio = '';
                        item.style.width = '';
                        item.style.height = '';
                        item.style.display = '';
                        item.style.alignItems = '';
                        item.style.justifyContent = '';

                        const img = item.querySelector('img');
                        if (img) {
                            img.style.width = '';
                            img.style.height = '';
                            img.style.objectFit = '';
                        }
                    });
                }
            }

            const discoverToggle = document.getElementById('discoverToggle');
            const discoverSection = document.querySelector('.discover-section');
            const discoverFormatSetting = document.getElementById('discoverFormatSetting');
            const discoverFormatSelect = document.getElementById('discoverFormatSelect');
            const discoverRoundedSetting = document.getElementById('discoverRoundedSetting');
            const discoverRoundedToggle = document.getElementById('discoverRoundedToggle');
            const discoverSizeSetting = document.getElementById('discoverSizeSetting');
            const discoverShapeSelect = document.getElementById('discoverShapeSelect');
            const discoverSizeSquare = document.getElementById('discoverSizeSquare');
            const discoverSizeRectangle = document.getElementById('discoverSizeRectangle');
            const discoverSizeRange = document.getElementById('discoverSizeRange');
            const discoverSizeInput = document.getElementById('discoverSizeInput');
            const discoverWidthRange = document.getElementById('discoverWidthRange');
            const discoverWidthInput = document.getElementById('discoverWidthInput');
            const discoverHeightRange = document.getElementById('discoverHeightRange');
            const discoverHeightInput = document.getElementById('discoverHeightInput');

            // 设置初始化由 loadUserPreferences() 函数处理，确保从服务器加载最新设置
            // 这些变量仅用于 API 失败时的回退，不再用于初始化
            const storedValue = localStorage.getItem('discoverEnabled');
            const discoverEnabled = storedValue === null ? true : storedValue === 'true';
            const storedFormat = localStorage.getItem('discoverFormat');
            const discoverFormat = storedFormat === null ? 'two' : storedFormat;
            const storedRounded = localStorage.getItem('discoverRounded');
            const discoverRounded = storedRounded === null ? true : storedRounded === 'true';
            const storedShape = localStorage.getItem('discoverShape');
            const discoverShape = storedShape === null ? 'square' : storedShape;
            const storedSize = localStorage.getItem('discoverSize');
            const discoverSize = storedSize ? JSON.parse(storedSize) : { width: 150, height: 150 };

            if (discoverEnabled) {
                discoverFormatSetting.classList.remove('disabled');
                discoverRoundedSetting.classList.remove('disabled');
                discoverSizeSetting.classList.remove('disabled');
                // 区块显示与图片加载统一由 loadRandomImages() 在渲染完成后处理
            } else {
                discoverSection.classList.remove('visible');
                discoverFormatSetting.classList.add('disabled');
                discoverRoundedSetting.classList.add('disabled');
                discoverSizeSetting.classList.add('disabled');
            }

            discoverToggle.addEventListener('change', function() {
                const isEnabled = this.checked;
                updateAndSavePreferences({ discover_enabled: isEnabled });

                if (isEnabled) {
                    discoverFormatSetting.classList.remove('disabled');
                    discoverRoundedSetting.classList.remove('disabled');
                    discoverSizeSetting.classList.remove('disabled');
                    loadRandomImages();
                } else {
                    discoverSection.classList.remove('visible');
                    discoverFormatSetting.classList.add('disabled');
                    discoverRoundedSetting.classList.add('disabled');
                    discoverSizeSetting.classList.add('disabled');
                }
            });

            discoverFormatSelect.addEventListener('change', function() {
                const format = this.value;
                updateAndSavePreferences({ discover_format: format });
                applyDiscoverFormat(format);
            });

            discoverRoundedToggle.addEventListener('change', function() {
                const isEnabled = this.checked;
                updateAndSavePreferences({ discover_rounded: isEnabled });
                applyDiscoverRounded();
            });

            discoverShapeSelect.addEventListener('change', function() {
                const shape = this.value;
                updateAndSavePreferences({ discover_shape: shape });

                if (shape === 'rectangle') {
                    discoverSizeSquare.style.display = 'none';
                    discoverSizeRectangle.style.display = 'block';
                } else {
                    discoverSizeSquare.style.display = 'block';
                    discoverSizeRectangle.style.display = 'none';
                }
                applyDiscoverSize();
            });

            discoverSizeRange.addEventListener('input', function() {
                discoverSizeInput.value = this.value;
                // 与数字输入框一致：滑块改动同样保存到用户偏好（此前仅写 localStorage，刷新丢设置）
                updateAndSavePreferences({
                    discover_size: { width: parseInt(this.value), height: parseInt(this.value) }
                });
                applyDiscoverSize();
            });

            discoverSizeInput.addEventListener('input', function() {
                let value = parseInt(this.value);
                if (value < 100) value = 100;
                if (value > 400) value = 400;
                discoverSizeRange.value = value;
                updateAndSavePreferences({ discover_size: { width: value, height: value } });
                applyDiscoverSize();
            });

            discoverWidthRange.addEventListener('input', function() {
                discoverWidthInput.value = this.value;
                const height = parseInt(discoverHeightInput.value);
                updateAndSavePreferences({ discover_size: { width: parseInt(this.value), height: height } });
                applyDiscoverSize();
            });

            discoverWidthInput.addEventListener('input', function() {
                let value = parseInt(this.value);
                if (value < 100) value = 100;
                if (value > 500) value = 500;
                discoverWidthRange.value = value;
                const height = parseInt(discoverHeightInput.value);
                updateAndSavePreferences({ discover_size: { width: value, height: height } });
                applyDiscoverSize();
            });

            discoverHeightRange.addEventListener('input', function() {
                discoverHeightInput.value = this.value;
                const width = parseInt(discoverWidthInput.value);
                updateAndSavePreferences({ discover_size: { width: width, height: parseInt(this.value) } });
                applyDiscoverSize();
            });

            discoverHeightInput.addEventListener('input', function() {
                let value = parseInt(this.value);
                if (value < 100) value = 100;
                if (value > 500) value = 500;
                discoverHeightRange.value = value;
                const width = parseInt(discoverWidthInput.value);
                updateAndSavePreferences({ discover_size: { width: width, height: value } });
                applyDiscoverSize();
            });

            document.getElementById('resetSettingsBtn').addEventListener('click', function() {
                if (confirm('确定要恢复所有设置为默认值吗？')) {
                    // 清除 localStorage
                    localStorage.removeItem('discoverEnabled');
                    localStorage.removeItem('discoverFormat');
                    localStorage.removeItem('discoverRounded');
                    localStorage.removeItem('discoverShape');
                    localStorage.removeItem('discoverSize');
                    localStorage.removeItem('sidebarTransparent');
                    localStorage.removeItem('pagePadding');

                    // 清除服务器上的用户设置
                    saveUserPreferences({});

                    // 重置 userPreferences
                    userPreferences = {};

                    // 重新加载页面
                    location.reload();
                }
            });

            const sidebarTransparentSelect = document.getElementById('sidebarTransparentSelect');
            // sidebarTransparent 的初始化由 loadUserPreferences() 函数处理

            sidebarTransparentSelect.addEventListener('change', function() {
                const opacity = this.value;
                updateAndSavePreferences({ sidebar_transparency: opacity });
                updateSidebarTransparency(opacity);
            });

            function updateSidebarTransparency(opacity) {
                if (opacity === '100') {
                    sidebar.style.background = 'white';
                    sidebar.style.backdropFilter = 'none';
                } else {
                    const alpha = parseInt(opacity) / 100;
                    sidebar.style.background = `rgba(255, 255, 255, ${alpha})`;
                    sidebar.style.backdropFilter = 'blur(10px)';
                }
            }

            // 左右留空设置
            const paddingRange = document.getElementById('paddingRange');
            const paddingInput = document.getElementById('paddingInput');

            // 加载保存的设置，默认为 60px
            const storedPadding = localStorage.getItem('pagePadding');
            const pagePadding = storedPadding ? parseInt(storedPadding) : 60;

            if (storedPadding) {
                paddingRange.value = pagePadding;
                paddingInput.value = pagePadding;
            }

            // 滑块变化事件
            paddingRange.addEventListener('input', function() {
                const value = parseInt(this.value);
                paddingInput.value = value;
                localStorage.setItem('pagePadding', value);
                applyPagePadding(value);
            });

            // 数值输入变化事件
            paddingInput.addEventListener('input', function() {
                let value = parseInt(this.value);
                if (value < 0) value = 0;
                if (value > 200) value = 200;
                paddingRange.value = value;
                localStorage.setItem('pagePadding', value);
                applyPagePadding(value);
            });

            // 应用左右留空
            function applyPagePadding(padding) {
                if (!isMobile) {
                    document.body.style.padding = `10px ${padding}px`;
                }
            }

            window.addEventListener('resize', function() {
                const wasMobile = isMobile;
                isMobile = window.innerWidth <= 768;

                if (wasMobile !== isMobile) {
                    const discoverEnabled = discoverToggle.checked;
                    if (discoverEnabled && discoverSection.classList.contains('visible')) {
                        applyDiscoverFormat(discoverFormatSelect.value);
                        applyDiscoverRounded();
                        applyDiscoverSize();
                    }
                    // 重新应用左右留空设置
                    const currentPadding = parseInt(paddingInput.value);
                    applyPagePadding(currentPadding);
                }
            });

            // 收藏按钮点击事件
            document.getElementById('lightboxFavorite').addEventListener('click', function() {
                const lightboxImage = document.getElementById('lightboxImage');
                toggleFavorite(lightboxImage.src);
            });

            // 发现图片渲染完成后重新应用显示设置（格式/圆角/尺寸）
            window.addEventListener('discover:images-rendered', function() {
                const fmtSelect = document.getElementById('discoverFormatSelect');
                applyDiscoverFormat(fmtSelect ? fmtSelect.value : 'two');
                applyDiscoverRounded();
                applyDiscoverSize();
            });

            // 收藏入口点击事件
            document.addEventListener('click', function(e) {
                const favoritesItem = e.target.closest('.gallery-item[data-type="favorites"]');
                if (favoritesItem) {
                    window.location.href = '/gallery/favorites';
                }
            });

            if (isMobile) {
                setupTouchZoom();
                setupDoubleTap();
                setupSwipeNavigation();
            }
        });

        function openLightbox(url) {
            const lightbox = document.getElementById('lightbox');
            const lightboxImage = document.getElementById('lightboxImage');
            const lightboxName = document.getElementById('lightboxName');
            const lightboxFavorite = document.getElementById('lightboxFavorite');

            lightboxImage.src = url;
            lightbox.classList.add('active');
            document.body.style.overflow = 'hidden';

            const fileName = url.split('/').pop();
            lightboxName.textContent = fileName || '图片';

            if (window._discoverImages) {
                window._discoverCurrentIndex = window._discoverImages.indexOf(url);
            }

            // 检查收藏状态
            checkFavoriteStatus(url);

            resetZoom();
        }

        function showPrevDiscoveryImage() {
            switchDiscoveryImage(-1);
        }

        function showNextDiscoveryImage() {
            switchDiscoveryImage(1);
        }

        function switchDiscoveryImage(direction) {
            const list = window._discoverImages;
            if (!list || list.length === 0) return;
            let idx = window._discoverCurrentIndex;
            if (idx < 0) return; // 非发现图片（如画廊网格灯箱）不参与方向键切换
            idx = (idx + direction + list.length) % list.length;
            window._discoverCurrentIndex = idx;
            openLightbox(list[idx]);
        }

        function closeLightbox() {
            const lightbox = document.getElementById('lightbox');
            const lightboxImage = document.getElementById('lightboxImage');

            lightbox.classList.remove('active');
            document.body.style.overflow = 'auto';

            resetZoom();
            lightboxImage.src = '';
        }

        function zoomIn() {
            if (zoomLevel < maxZoom) {
                zoomLevel += 0.5;
                applyZoom();
            }
        }

        function zoomOut() {
            if (zoomLevel > 0.5) {
                zoomLevel -= 0.5;
                applyZoom();
            }
        }

        function resetZoom() {
            zoomLevel = 1;
            applyZoom();
        }

        function applyZoom() {
            const lightboxImage = document.getElementById('lightboxImage');
            lightboxImage.style.transform = `scale(${zoomLevel})`;
        }

        function setupTouchZoom() {
            const lightboxContent = document.querySelector('.lightbox-content');
            let initialDistance = 0;

            lightboxContent.addEventListener('touchstart', function(e) {
                if (e.touches.length === 2) {
                    initialDistance = getDistance(e.touches[0], e.touches[1]);
                }
            });

            lightboxContent.addEventListener('touchmove', function(e) {
                if (e.touches.length === 2) {
                    e.preventDefault();
                    const currentDistance = getDistance(e.touches[0], e.touches[1]);

                    if (initialDistance > 0) {
                        const scale = currentDistance / initialDistance;
                        zoomLevel = Math.min(Math.max(1, scale), maxZoom);
                        applyZoom();
                    }
                }
            });

            lightboxContent.addEventListener('touchend', function() {
                initialDistance = 0;
            });

            function getDistance(touch1, touch2) {
                const dx = touch1.clientX - touch2.clientX;
                const dy = touch1.clientY - touch2.clientY;
                return Math.sqrt(dx * dx + dy * dy);
            }
        }

        function setupDoubleTap() {
            const lightboxImage = document.getElementById('lightboxImage');
            let lastTap = 0;

            lightboxImage.addEventListener('touchstart', function(e) {
                const currentTime = new Date().getTime();
                const tapLength = currentTime - lastTap;

                if (tapLength < 300 && tapLength > 0) {
                    e.preventDefault();
                    if (zoomLevel === 1) {
                        zoomLevel = 2;
                    } else {
                        zoomLevel = 1;
                    }
                    applyZoom();
                }

                lastTap = currentTime;
            });
        }

        function setupSwipeNavigation() {
            var lightbox = document.getElementById('lightbox');
            var lightboxImage = document.getElementById('lightboxImage');
            var touchStartX = 0;
            var touchStartY = 0;
            var currentX = 0;
            var isSwiping = false;
            var isAnimating = false;

            lightbox.addEventListener('touchstart', function(e) {
                if (isAnimating) return;
                if (e.touches.length === 1) {
                    touchStartX = e.changedTouches[0].screenX;
                    touchStartY = e.changedTouches[0].screenY;
                    currentX = 0;
                    isSwiping = true;
                    lightboxImage.style.transition = 'none';
                }
            }, { passive: true });

            lightbox.addEventListener('touchmove', function(e) {
                if (!isSwiping || e.touches.length !== 1) return;
                var diffX = e.changedTouches[0].screenX - touchStartX;
                var diffY = Math.abs(e.changedTouches[0].screenY - touchStartY);
                if (diffY > Math.abs(diffX) * 1.5) {
                    isSwiping = false;
                    lightboxImage.style.transform = '';
                    return;
                }
                currentX = diffX;
                lightboxImage.style.transform = 'translateX(' + diffX + 'px)';
            }, { passive: true });

            lightbox.addEventListener('touchend', function(e) {
                if (!isSwiping) return;
                isSwiping = false;
                if (Math.abs(currentX) > 50) {
                    isAnimating = true;
                    var dir = currentX > 0 ? -1 : 1;
                    var list = window._discoverImages;
                    var idx = window._discoverCurrentIndex;
                    if (!list || idx < 0) { isAnimating = false; lightboxImage.style.transform = ''; return; }
                    var nextIdx = (idx + dir + list.length) % list.length;
                    var nextUrl = list[nextIdx];
                    var preload = new Image();
                    preload.onload = function() {
                        var imgW = window.innerWidth;
                        lightboxImage.style.transition = 'transform 0.25s ease-out';
                        lightboxImage.style.transform = 'translateX(' + (-dir * imgW) + 'px)';
                        setTimeout(function() {
                            lightboxImage.src = nextUrl;
                            window._discoverCurrentIndex = (window._discoverCurrentIndex + dir + list.length) % list.length;
                            var fn = nextUrl.split('/').pop();
                            var nm = document.getElementById('lightboxName');
                            if (nm) nm.textContent = fn || '';
                            checkFavoriteStatus(nextUrl);
                            lightboxImage.style.transition = 'none';
                            lightboxImage.style.transform = 'translateX(' + (dir * imgW) + 'px)';
                            void lightboxImage.offsetWidth;
                            lightboxImage.style.transition = 'transform 0.25s ease-out';
                            lightboxImage.style.transform = '';
                            setTimeout(function() { isAnimating = false; }, 250);
                        }, 250);
                    };
                    preload.src = nextUrl;
                } else {
                    lightboxImage.style.transition = 'transform 0.2s ease-out';
                    lightboxImage.style.transform = '';
                }
            }, { passive: true });
        }

        // 收藏相关函数
        function extractImagePath(imageUrl) {
            if (!imageUrl) return '';
            let imagePath = imageUrl;
            if (imageUrl.startsWith('http')) {
                try {
                    const urlObj = new URL(imageUrl);
                    imagePath = urlObj.pathname;
                } catch (e) {}
            }
            imagePath = imagePath.replace(/^\/gallery\/image\//, '');
            imagePath = imagePath.replace(/^\/+/, '');
            try {
                imagePath = decodeURIComponent(imagePath);
            } catch (e) {}
            return imagePath;
        }

        function checkFavoriteStatus(imageUrl) {
            const imagePath = extractImagePath(imageUrl);
            if (!imagePath) return;
            
            fetch('/gallery/api/favorite/check', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': getCsrfToken()
                },
                body: JSON.stringify({ path: imagePath })
            })
            .then(response => response.json())
            .then(data => {
                const lightboxFavorite = document.getElementById('lightboxFavorite');
                if (data.is_favorite) {
                    lightboxFavorite.classList.add('active');
                } else {
                    lightboxFavorite.classList.remove('active');
                }
            })
            .catch(error => {
                console.error('检查收藏状态失败:', error);
            });
        }

        function toggleFavorite(imageUrl) {
            const imagePath = extractImagePath(imageUrl);
            if (!imagePath) {
                showNotification('无效的图片路径');
                return;
            }
            
            const lightboxFavorite = document.getElementById('lightboxFavorite');
            const isFavorite = lightboxFavorite.classList.contains('active');

            const apiUrl = isFavorite ? '/gallery/api/favorite/remove' : '/gallery/api/favorite/add';

            fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': getCsrfToken()
                },
                body: JSON.stringify({ path: imagePath })
            })
            .then(response => {
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    if (isFavorite) {
                        lightboxFavorite.classList.remove('active');
                        showNotification('已取消收藏');
                    } else {
                        lightboxFavorite.classList.add('active');
                        showNotification('收藏成功');
                    }
                } else {
                    showNotification(data.message || '操作失败');
                }
            })
            .catch(error => {
                console.error('收藏操作失败:', error);
                showNotification('操作失败，请重试');
            });
        }

        function showNotification(message) {
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed;
                top: 80px;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 12px 24px;
                border-radius: 4px;
                z-index: 3000;
                animation: fadeInOut 2s ease-in-out;
            `;
            notification.textContent = message;
            document.body.appendChild(notification);

            setTimeout(() => {
                notification.remove();
            }, 2000);
        }

        // 添加 fadeInOut 动画
        const style = document.createElement('style');
        style.textContent = `
            @keyframes fadeInOut {
                0% { opacity: 0; }
                20% { opacity: 1; }
                80% { opacity: 1; }
                100% { opacity: 0; }
            }
        `;
        document.head.appendChild(style);

        function loadRandomImages() {
            const discoverGallery = document.getElementById('discoverGallery');
            const discoverSection = document.querySelector('.discover-section');

            fetch('/gallery/api/random-images')
                .then(response => response.json())
                .then(data => {
                    window._discoverImages = data.images || [];
                    if (data.images && data.images.length > 0) {
                        // 先在空网格上应用最终布局参数（通过事件在持有这些设置的闭包内执行），
                        // 再一次性插入，保证首次绘制即为最终形态（消除布局跳动）
                        window.dispatchEvent(new CustomEvent('discover:images-rendered'));

                        const fragment = document.createDocumentFragment();
                        data.images.forEach((imageUrl, index) => {
                            const item = document.createElement('div');
                            item.className = 'discover-item';
                            // 前8张图片使用eager loading，确保快速滑动时图片已就绪
                            const loadingAttr = index < 8 ? 'eager' : 'lazy';
                            item.innerHTML = `<img src="${escapeHtml(imageUrl)}" alt="随机图片" loading="${loadingAttr}">`;
                            item.addEventListener('click', function() {
                                window._discoverCurrentIndex = index;
                                openLightbox(imageUrl);
                            });
                            fragment.appendChild(item);
                        });
                        discoverGallery.replaceChildren(fragment);

                        // 插入后再通知一次：把尺寸参数应用到新的 item 上
                        // （两次派发同步执行、同帧完成，浏览器只绘制最终状态）
                        window.dispatchEvent(new CustomEvent('discover:images-rendered'));

                        // 追踪所有发现图片是否加载完成，用于控制底部提示的显示
                        galleryBottomHintTrackLoaded();

                        // 为新渲染的发现缩略图绑定加载淡入
                        bindThumbnailFade();

                        // 渲染完成后才显示发现区（消除加载前后的布局跳动）
                        if (discoverSection) discoverSection.classList.add('visible');
                    } else {
                        discoverGallery.innerHTML = '<div class="loading">暂无图片</div>';
                        if (discoverSection) discoverSection.classList.add('visible');
                        window._discoverAllLoaded = true;
                        if (window._updateDiscoverHint) window._updateDiscoverHint();
                    }
                })
                .catch(error => {
                    console.error('加载随机图片失败:', error);
                    discoverGallery.innerHTML = '<div class="loading">加载失败</div>';
                    if (discoverSection) discoverSection.classList.add('visible');
                    window._discoverAllLoaded = true;
                    if (window._updateDiscoverHint) window._updateDiscoverHint();
                });
        }

        // 追踪发现图片是否全部加载完成（含懒加载的图片）
        function galleryBottomHintTrackLoaded() {
            const discoverGallery = document.getElementById('discoverGallery');
            const images = discoverGallery.querySelectorAll('.discover-item img');
            const total = images.length;
            let loaded = 0;

            window._discoverAllLoaded = total === 0;
            if (total === 0) {
                if (window._updateDiscoverHint) window._updateDiscoverHint();
                return;
            }

            function markLoaded() {
                loaded += 1;
                if (loaded >= total) {
                    window._discoverAllLoaded = true;
                    if (window._updateDiscoverHint) window._updateDiscoverHint();
                }
            }

            images.forEach(function(img) {
                if (img.complete && img.naturalWidth > 0) {
                    markLoaded();
                } else {
                    img.addEventListener('load', markLoaded, { once: true });
                    img.addEventListener('error', markLoaded, { once: true });
                }
            });
        }

        // 为缩略图绑定加载淡入：加载完成前 opacity:0，避免加载瞬间被压成方形/拉伸
        function bindThumbnailFade() {
            document.querySelectorAll('.gallery-image, .discover-item img').forEach(function(img) {
                if (img.classList.contains('loaded')) return;
                const done = function() { img.classList.add('loaded'); };
                if (img.complete && img.naturalWidth > 0) {
                    done();
                } else {
                    img.addEventListener('load', done, { once: true });
                    img.addEventListener('error', done, { once: true });
                }
            });
            setupNearPreload();
        }

        // 扩大图片预加载范围：视口较远的图片提前从 lazy 提升为 eager，
        // 让快速滚动时图片已就绪，避免出现大片白色/空白区域
        // 注意：只对未加载完成的图片提升，避免浏览器重新请求已加载的图片
        function setupNearPreload() {
            if (!window._nearPreloadObserver) {
                if (!('IntersectionObserver' in window)) return;
                window._nearPreloadObserver = new IntersectionObserver(function(entries) {
                    entries.forEach(function(entry) {
                        const img = entry.target;
                        if (entry.isIntersecting) {
                            // 只对未加载完成的 lazy 图片提升为 eager，避免重新请求已加载的图片
                            if (img.loading === 'lazy' && !img.complete) {
                                img.loading = 'eager';
                            }
                            window._nearPreloadObserver.unobserve(img);
                        }
                    });
                }, { rootMargin: '2000px 0px' });
            }
            // 只观察尚未加载完成的懒加载图片
            document.querySelectorAll('.gallery-image, .discover-item img').forEach(function(img) {
                if (img.loading === 'lazy' && !img.complete) {
                    window._nearPreloadObserver.observe(img);
                }
            });
        }

        // 页面初始的缩略图（主图库 / 文件夹封面）绑定加载淡入
        bindThumbnailFade();

        function initDiscoverReloadHint() {
            const sentinel = document.getElementById('discoverBottomSentinel');
            const hint = document.getElementById('discoverReloadHint');
            if (!sentinel || !hint) return;
            if (!('IntersectionObserver' in window)) return;
            // 记录哨兵是否进入视口，仅当所有发现图片都已加载时才显示底部提示
            let atBottom = false;
            window._updateDiscoverHint = function() {
                hint.style.display = (window._discoverAllLoaded === true && atBottom) ? 'block' : 'none';
            };
            const observer = new IntersectionObserver(function(entries) {
                entries.forEach(function(entry) {
                    atBottom = entry.isIntersecting;
                    window._updateDiscoverHint();
                });
            }, { threshold: 0 });
            observer.observe(sentinel);
        }

        // 初始化发现区到底提示
        initDiscoverReloadHint();
    