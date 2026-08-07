document.addEventListener('DOMContentLoaded', () => {
    async function createDeviceFingerprint() {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        if (context) {
            context.textBaseline = 'top';
            context.font = '16px Arial';
            context.fillStyle = '#f60';
            context.fillRect(20, 1, 62, 20);
            context.fillStyle = '#069';
            context.fillText('xoan-device-check', 2, 15);
        }
        const sides = [screen.width, screen.height].sort((a, b) => a - b);
        const signals = [
            navigator.userAgent,
            navigator.platform,
            navigator.language,
            Intl.DateTimeFormat().resolvedOptions().timeZone,
            sides.join('x'),
            screen.colorDepth,
            navigator.hardwareConcurrency || 0,
            navigator.deviceMemory || 0,
            navigator.maxTouchPoints || 0,
            canvas.toDataURL()
        ].join('|');
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(signals));
        return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    }

    const deviceIdPromise = createDeviceFingerprint();
    // Parallax effect on mouse move for the hero section
    const heroVisual = document.querySelector('.hero-visual');
    const parallaxElements = document.querySelectorAll('.parallax');

    if (heroVisual && window.innerWidth > 1024) {
        heroVisual.addEventListener('mousemove', (e) => {
            const x = e.clientX / window.innerWidth;
            const y = e.clientY / window.innerHeight;

            parallaxElements.forEach(el => {
                const speed = parseFloat(el.getAttribute('data-speed'));
                const xOffset = (window.innerWidth / 2 - e.clientX) * (speed / 100);
                const yOffset = (window.innerHeight / 2 - e.clientY) * (speed / 100);
                
                el.style.transform = `translate(${xOffset}px, ${yOffset}px)`;
            });
        });

        // Reset transform on mouse leave
        heroVisual.addEventListener('mouseleave', () => {
            parallaxElements.forEach(el => {
                el.style.transform = `translate(0px, 0px)`;
            });
        });
    }

    // Activation Flow Logic
    const form = document.getElementById('activation-form');
    const input = document.getElementById('locket-username');
    const errorText = document.getElementById('error-message');
    const loadingText = document.getElementById('loading-text');
    
    const stepInput = document.getElementById('step-input');
    const stepLoading = document.getElementById('step-loading');
    const stepConfirm = document.getElementById('step-confirm');
    const stepSuccess = document.getElementById('step-success');
    
    const successUsername = document.getElementById('success-username');
    const confirmUsername = document.getElementById('confirm-username');
    const confirmStatus = document.getElementById('confirm-status');
    
    const btnActivate = document.getElementById('btn-activate');
    const btnCancel = document.getElementById('btn-cancel');
    const btnReset = document.getElementById('btn-reset');

    const paymentPrompt = document.getElementById('payment-prompt');
    const paymentQr = document.getElementById('payment-qr');
    const paymentLink = document.getElementById('payment-link');
    const paymentInstruction = document.getElementById('payment-instruction');
    const paymentOrderId = document.getElementById('payment-order-id');
    const paymentAccount = document.getElementById('payment-account');
    const paymentAmount = document.getElementById('payment-amount');
    const shareUnlockButton = document.getElementById('share-unlock-button');

    const referrerCode = new URLSearchParams(window.location.search).get('ref');
    let currentUid = null;
    let textInterval = null;
    let paymentPollTimer = null;

    function showStep(stepElement) {
        document.querySelectorAll('.widget-step').forEach(el => el.classList.remove('active'));
        stepElement.classList.add('active');
    }

    function showError(msg) {
        errorText.textContent = msg;
        errorText.style.display = 'block';
        showStep(stepInput);
    }

    function getApiOrigin() {
        if (window.location.protocol.startsWith('http')) {
            return window.location.origin;
        }
        return 'http://127.0.0.1:8080';
    }

    async function fetchApi(path, options) {
        const origins = [getApiOrigin(), 'http://localhost:8080', 'http://127.0.0.1:8080'];
        let lastError = null;

        for (const origin of origins) {
            try {
                const url = origin.endsWith('/') ? `${origin}${path.replace(/^\//, '')}` : `${origin}${path}`;
                const response = await fetch(url, options);

                if (response.ok) {
                    return response;
                }

                const contentType = response.headers.get('Content-Type') || '';
                if (contentType.includes('application/json')) {
                    return response;
                }

                lastError = new Error(`Unexpected response from ${origin}: ${response.status}`);
            } catch (error) {
                lastError = error;
            }
        }

        throw lastError;
    }

    function stopPaymentPolling() {
        if (paymentPollTimer) {
            clearInterval(paymentPollTimer);
            paymentPollTimer = null;
        }
    }

    function startPaymentPolling(orderId, deviceId) {
        stopPaymentPolling();
        let checking = false;
        paymentPollTimer = setInterval(async () => {
            if (checking) return;
            checking = true;
            try {
                const response = await fetchApi(`/api/payment-status?order_id=${encodeURIComponent(orderId)}&device_id=${encodeURIComponent(deviceId)}`, {
                    method: 'GET',
                    cache: 'no-store'
                });
                const status = await response.json();
                if (response.ok && (status.paid || status.unlocked)) {
                    stopPaymentPolling();
                    paymentInstruction.textContent = `Mở khóa thành công! Bạn có ${status.remaining_uses || 3} lượt trong 7 ngày. Hệ thống đang tiếp tục kích hoạt...`;
                    paymentInstruction.style.color = '#15803d';
                    paymentInstruction.style.fontWeight = '700';
                    setTimeout(() => btnActivate.click(), 2000);
                }
            } catch (error) {
                // Keep polling: a short network interruption should not lose the payment flow.
            } finally {
                checking = false;
            }
        }, 3000);
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = input.value.trim();
        
        if (username.length < 3) {
            errorText.textContent = "Vui lòng nhập Username hoặc Link hợp lệ.";
            errorText.style.display = 'block';
            return;
        }

        errorText.style.display = 'none';
        showStep(stepLoading);

        loadingText.textContent = "Đang kiểm tra tài khoản...";

        const normalizedUsername = username.replace(/^https?:\/\//i, '')
            .replace(/^www\./i, '')
            .replace(/.*locket\.cam\//i, '')
            .split(/[?#]/)[0]
            .trim();

        try {
            const response = await fetchApi('/api/check_user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: normalizedUsername })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                currentUid = data.uid;
                confirmUsername.textContent = data.username || normalizedUsername;
                
                if (data.has_gold) {
                    confirmStatus.textContent = "Đã có Gold";
                    confirmStatus.className = "status-badge has-gold";
                } else {
                    confirmStatus.textContent = "Chưa có Gold";
                    confirmStatus.className = "status-badge no-gold";
                }
                
                showStep(stepConfirm);
            } else {
                showError(data.message || "Không tìm thấy tài khoản!");
            }
        } catch (error) {
            showError("Lỗi kết nối máy chủ.");
        }
    });

    if (btnActivate) {
        btnActivate.addEventListener('click', async () => {
            if (!currentUid) return;
            const deviceId = await deviceIdPromise;
            
            showStep(stepLoading);
            
            const loadingTexts = [
                "Đang gửi yêu cầu kích hoạt...",
                "Đang kết nối RevenueCat...",
                "Đang xác thực gói Premium..."
            ];
            
            let textIndex = 0;
            loadingText.textContent = loadingTexts[0];
            
            textInterval = setInterval(() => {
                textIndex = (textIndex + 1) % loadingTexts.length;
                loadingText.textContent = loadingTexts[textIndex];
            }, 1500);

            try {
                const response = await fetchApi('/api/activate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        uid: currentUid,
                        device_id: deviceId,
                        referrer_code: referrerCode
                    })
                });

                const data = await response.json();
                clearInterval(textInterval);

                if (response.ok && data.success) {
                    stopPaymentPolling();
                    successUsername.textContent = confirmUsername.textContent;
                    const dnsLink = document.getElementById('dns-link');
                    if (dnsLink) {
                        const finalUrl = data.dns_url || 'https://tinyurl.com/45z362ae';
                        dnsLink.href = finalUrl;
                        dnsLink.setAttribute('data-url', finalUrl);
                        dnsLink.textContent = 'Tải Cấu hình DNS';
                    }
                    if (paymentPrompt) {
                        paymentPrompt.style.display = 'none';
                    }
                    showStep(stepSuccess);
                } else if (response.status === 403 && data.payment_url) {
                    if (paymentPrompt) {
                        paymentPrompt.style.display = 'block';
                    }
                    if (paymentLink) {
                        paymentLink.href = data.payment_url;
                    }
                    if (paymentQr) {
                        paymentQr.replaceChildren();
                        const qrImage = document.createElement('img');
                        qrImage.src = data.payment_qr_url || data.payment_url;
                        qrImage.alt = `QR thanh toán đơn ${data.order_id}`;
                        qrImage.style.cssText = 'width:280px;max-width:100%;height:auto;';
                        paymentQr.appendChild(qrImage);
                    }
                    if (paymentOrderId) paymentOrderId.textContent = data.order_id;
                    if (paymentAccount) paymentAccount.textContent = `${data.bank_code} - ${data.account_no}${data.account_name ? ` - ${data.account_name}` : ''}`;
                    if (paymentAmount) paymentAmount.textContent = `${Number(data.amount || 0).toLocaleString('vi-VN')}đ`;
                    paymentInstruction.textContent = 'Đang chờ ngân hàng xác nhận. Vui lòng giữ nguyên số tiền và nội dung chuyển khoản.';
                    paymentInstruction.style.color = '#5b4a2f';
                    paymentInstruction.style.fontWeight = '400';
                    if (shareUnlockButton && data.referral_code) {
                        const shareUrl = `${window.location.origin}${window.location.pathname}?ref=${encodeURIComponent(data.referral_code)}`;
                        shareUnlockButton.style.display = 'inline-flex';
                        shareUnlockButton.onclick = async () => {
                            const shareData = {
                                title: 'Dùng thử Xoăn Locket',
                                text: 'Mở link và kích hoạt một lần để người giới thiệu nhận 1 lượt.',
                                url: shareUrl
                            };
                            try {
                                if (navigator.share) {
                                    await navigator.share(shareData);
                                } else {
                                    await navigator.clipboard.writeText(shareUrl);
                                    paymentInstruction.textContent = 'Đã sao chép link. Khi một thiết bị khác kích hoạt thành công, bạn sẽ nhận 1 lượt.';
                                }
                            } catch (error) {
                                // User cancelled the native share sheet.
                            }
                        };
                    }
                    startPaymentPolling(data.order_id, deviceId);
                    showStep(stepInput);
                    errorText.style.display = 'none';
                } else {
                    showError(data.message || "Lỗi hệ thống. Vui lòng thử lại!");
                }
            } catch (error) {
                clearInterval(textInterval);
                showError("Không thể kết nối tới máy chủ. Vui lòng thử lại sau.");
            }
        });
    }

    if (btnCancel) {
        btnCancel.addEventListener('click', () => {
            stopPaymentPolling();
            input.value = '';
            currentUid = null;
            showStep(stepInput);
        });
    }

    btnReset.addEventListener('click', () => {
        stopPaymentPolling();
        input.value = '';
        currentUid = null;
        errorText.style.display = 'none';
        showStep(stepInput);
    });

    // --- Scroll Reveal Animation ---
    const revealElements = document.querySelectorAll('.reveal-up');
    
    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                // Optional: Stop observing once revealed
                observer.unobserve(entry.target);
            }
        });
    }, {
        root: null,
        rootMargin: '0px',
        threshold: 0.15
    });

    revealElements.forEach(el => {
        revealObserver.observe(el);
    });

    // --- FAQ Accordion ---
    const faqItems = document.querySelectorAll('.faq-item');
    
    faqItems.forEach(item => {
        const question = item.querySelector('.faq-question');
        const answer = item.querySelector('.faq-answer');
        
        question.addEventListener('click', () => {
            const isActive = item.classList.contains('active');
            
            // Close all others
            faqItems.forEach(otherItem => {
                otherItem.classList.remove('active');
                otherItem.querySelector('.faq-answer').style.maxHeight = null;
            });
            
            // Toggle current
            if (!isActive) {
                item.classList.add('active');
                answer.style.maxHeight = answer.scrollHeight + "px";
            }
        });
    });

    // --- Premium UI Enhancements ---

    // 1. Scroll Progress & Navbar Scrolled State
    const progressBar = document.querySelector('.scroll-progress-bar');
    const navbar = document.querySelector('.navbar');

    window.addEventListener('scroll', () => {
        // Progress bar
        const windowHeight = document.documentElement.scrollHeight - document.documentElement.clientHeight;
        const scrolled = (window.scrollY / windowHeight) * 100;
        if (progressBar) progressBar.style.width = scrolled + '%';

        // Navbar blur
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });

    // 2. Cursor Glow Effect (Desktop Only)
    const cursorGlow = document.querySelector('.cursor-glow');
    let isDesktop = window.matchMedia("(min-width: 1024px) and (pointer: fine)").matches;
    let prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (cursorGlow && isDesktop && !prefersReducedMotion) {
        let cursorX = 0;
        let cursorY = 0;
        
        window.addEventListener('mousemove', (e) => {
            cursorX = e.clientX;
            cursorY = e.clientY;
            
            // Unhide after first move
            if (cursorGlow.style.opacity === '' || cursorGlow.style.opacity === '0') {
                cursorGlow.style.opacity = '1';
            }
        });
        
        // Use requestAnimationFrame for smooth cursor movement
        const updateCursor = () => {
            cursorGlow.style.transform = `translate(calc(${cursorX}px - 50%), calc(${cursorY}px - 50%))`;
            requestAnimationFrame(updateCursor);
        };
        requestAnimationFrame(updateCursor);
    }
    
    // 3. Update existing Hero Parallax to prevent conflict and add 3D tilt
    const newHeroVisual = document.querySelector('.hero-visual');
    const newParallaxElements = document.querySelectorAll('.parallax');
    const phoneMockup = document.querySelector('.phone-mockup');
    
    if (newHeroVisual && isDesktop && !prefersReducedMotion) {
        newHeroVisual.addEventListener('mousemove', (e) => {
            const rect = newHeroVisual.getBoundingClientRect();
            // Calculate mouse position relative to hero visual center (-1 to 1)
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const mouseX = (e.clientX - centerX) / (rect.width / 2);
            const mouseY = (e.clientY - centerY) / (rect.height / 2);

            // Floating elements parallax
            newParallaxElements.forEach(el => {
                if (el.classList.contains('phone-mockup')) return; // handled separately
                const speed = parseFloat(el.getAttribute('data-speed')) || 10;
                const xOffset = -mouseX * speed;
                const yOffset = -mouseY * speed;
                el.style.transform = `translate(${xOffset}px, ${yOffset}px)`;
            });

            // 3D Tilt for phone mockup
            if (phoneMockup) {
                // limit tilt to max 4 degrees
                const rotateX = -mouseY * 4;
                const rotateY = mouseX * 4;
                // pause the float animation while hovering
                phoneMockup.style.animation = 'none';
                phoneMockup.style.transform = `translateY(0) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
            }
        });

        newHeroVisual.addEventListener('mouseleave', () => {
            newParallaxElements.forEach(el => {
                if (el.classList.contains('phone-mockup')) return;
                el.style.transform = `translate(0px, 0px)`;
            });
            if (phoneMockup) {
                phoneMockup.style.transform = `translateY(0) rotateX(2deg) rotateY(-5deg)`;
                // restart float animation
                setTimeout(() => {
                    phoneMockup.style.animation = 'phoneFloat 8s ease-in-out infinite alternate';
                }, 300);
            }
        });
    }

    // 4. Magnetic Buttons
    const magneticBtns = document.querySelectorAll('.magnetic-btn');
    magneticBtns.forEach(btn => {
        if (prefersReducedMotion || !isDesktop) return;
        let bounds = btn.getBoundingClientRect();
        
        btn.addEventListener('mouseenter', () => {
            bounds = btn.getBoundingClientRect();
        });

        btn.addEventListener('mousemove', (e) => {
            const x = e.clientX - bounds.left;
            const y = e.clientY - bounds.top;
            
            const xWalk = (x - bounds.width / 2) * 0.3;
            const yWalk = (y - bounds.height / 2) * 0.3;
            
            btn.style.transform = `translate(${xWalk}px, ${yWalk}px)`;
            
            const btnText = btn.querySelector('.btn-text');
            if (btnText) {
                btnText.style.transform = `translate(${xWalk * 0.5}px, ${yWalk * 0.5}px)`;
            }
        });

        btn.addEventListener('mouseleave', () => {
            btn.style.transform = '';
            const btnText = btn.querySelector('.btn-text');
            if (btnText) {
                btnText.style.transform = '';
            }
        });
    });

    // 5. Dynamic Spotlight Border (Linear style)
    const dynamicCards = document.querySelectorAll('.dynamic-card');
    dynamicCards.forEach(card => {
        if (prefersReducedMotion || !isDesktop) return;
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
        });
    });

    // ============================================================
    // ELITE TIER EFFECTS - XOAN.LOCKET
    // ============================================================
    if (!prefersReducedMotion) {

        // --- 1. Neon Trail Cursor ---
        if (isDesktop) {
            const colors = ['#F4C95D', '#E29B35', '#D4AF37', '#FFF0B3', '#C08A38'];
            const trailDots = [];
            const TRAIL_LENGTH = 12;
            let mouseTrailX = 0, mouseTrailY = 0;
            const positions = Array(TRAIL_LENGTH).fill({ x: 0, y: 0 });

            for (let i = 0; i < TRAIL_LENGTH; i++) {
                const dot = document.createElement('div');
                dot.className = 'trail-dot';
                const size = Math.max(3, 10 - i * 0.7);
                dot.style.width = size + 'px';
                dot.style.height = size + 'px';
                dot.style.background = colors[i % colors.length];
                dot.style.opacity = (1 - i / TRAIL_LENGTH) * 0.7;
                dot.style.boxShadow = `0 0 ${size * 2}px ${colors[i % colors.length]}`;
                document.body.appendChild(dot);
                trailDots.push(dot);
            }

            window.addEventListener('mousemove', (e) => {
                mouseTrailX = e.clientX;
                mouseTrailY = e.clientY;
            });

            let trailPositions = Array.from({ length: TRAIL_LENGTH }, () => ({ x: 0, y: 0 }));
            const animateTrail = () => {
                trailPositions[0] = { x: mouseTrailX, y: mouseTrailY };
                for (let i = 1; i < TRAIL_LENGTH; i++) {
                    trailPositions[i] = {
                        x: trailPositions[i].x + (trailPositions[i - 1].x - trailPositions[i].x) * 0.35,
                        y: trailPositions[i].y + (trailPositions[i - 1].y - trailPositions[i].y) * 0.35,
                    };
                }
                trailDots.forEach((dot, i) => {
                    dot.style.left = trailPositions[i].x + 'px';
                    dot.style.top = trailPositions[i].y + 'px';
                });
                requestAnimationFrame(animateTrail);
            };
            requestAnimationFrame(animateTrail);
        }

        // --- 2. Ripple Click Effect ---
        const rippleColors = [
            'rgba(244,201,93,0.25)', 'rgba(226,155,53,0.2)',
            'rgba(212,175,55,0.2)', 'rgba(255,240,179,0.2)'
        ];
        let rippleColorIdx = 0;
        document.addEventListener('click', (e) => {
            // Don't ripple on form elements
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
            const ripple = document.createElement('div');
            ripple.className = 'ripple-effect';
            const size = 150 + Math.random() * 100;
            ripple.style.width = size + 'px';
            ripple.style.height = size + 'px';
            ripple.style.left = e.clientX + 'px';
            ripple.style.top = e.clientY + 'px';
            ripple.style.border = `2px solid ${rippleColors[rippleColorIdx % rippleColors.length]}`;
            ripple.style.background = rippleColors[rippleColorIdx % rippleColors.length];
            rippleColorIdx++;
            document.body.appendChild(ripple);
            ripple.addEventListener('animationend', () => ripple.remove());
        });

        // --- 3. Glitch Text Loop on Logo ---
        const glitchEls = document.querySelectorAll('.glitch-wrap');
        const triggerGlitch = () => {
            glitchEls.forEach(el => {
                el.classList.add('glitching');
                setTimeout(() => el.classList.remove('glitching'), 500);
            });
            // Schedule next glitch randomly between 3s and 8s
            setTimeout(triggerGlitch, 3000 + Math.random() * 5000);
        };
        setTimeout(triggerGlitch, 2000);

        // --- 4. Animated Counters (on scroll into view) ---
        const statNums = document.querySelectorAll('.stat-num[data-target]');
        const animateCounter = (el) => {
            const target = parseInt(el.getAttribute('data-target'));
            const suffix = el.getAttribute('data-suffix') || '';
            const duration = 1800;
            const startTime = performance.now();
            const easeOut = (t) => 1 - Math.pow(1 - t, 3);
            const tick = (now) => {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const current = Math.round(easeOut(progress) * target);
                el.textContent = current.toLocaleString('vi-VN') + suffix;
                if (progress < 1) requestAnimationFrame(tick);
                else el.textContent = target.toLocaleString('vi-VN') + suffix;
            };
            requestAnimationFrame(tick);
        };
        const counterObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    animateCounter(entry.target);
                    counterObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.3, rootMargin: '0px 0px -50px 0px' });
        statNums.forEach(el => counterObserver.observe(el));

        // --- 5. Typewriter Effect on Hero Subtitle ---
        const subtitle = document.querySelector('.hero-subtitle');
        if (subtitle) {
            const originalText = subtitle.textContent.trim();
            subtitle.textContent = '';
            const cursor = document.createElement('span');
            cursor.className = 'typewriter-cursor';
            subtitle.appendChild(cursor);
            let charIdx = 0;
            const typeNextChar = () => {
                if (charIdx < originalText.length) {
                    subtitle.insertBefore(document.createTextNode(originalText[charIdx]), cursor);
                    charIdx++;
                    setTimeout(typeNextChar, 28 + Math.random() * 20);
                }
            };
            // Delay start until hero is visible
            setTimeout(typeNextChar, 800);
        }

        // --- 6. Scroll-Linked Body Background (disabled - causes footer box illusion) ---
        // const bgColors = [ '#0a0a0a', '#0c0a10', '#0a0c12', '#0a0a0e', '#0c0a0a' ];
        // let lastBgIdx = 0;
        // window.addEventListener('scroll', () => { ... }, { passive: true });

    } // end if !prefersReducedMotion

});
