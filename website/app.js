document.addEventListener('DOMContentLoaded', () => {
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

    const referrerId = new URLSearchParams(window.location.search).get('ref');
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

    function startPaymentPolling(orderId) {
        stopPaymentPolling();
        let checking = false;
        paymentPollTimer = setInterval(async () => {
            if (checking) return;
            checking = true;
            try {
                const response = await fetchApi(`/api/payment-status?order_id=${encodeURIComponent(orderId)}`, {
                    method: 'GET',
                    cache: 'no-store'
                });
                const status = await response.json();
                if (response.ok && status.paid) {
                    stopPaymentPolling();
                    paymentInstruction.textContent = 'Thanh toán thành công! Giới hạn đã được mở lại. Hệ thống đang tiếp tục kích hoạt...';
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
                    body: JSON.stringify({ uid: currentUid, referrer_id: referrerId })
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
                    startPaymentPolling(data.order_id);
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
});
