import '@testing-library/jest-dom/vitest';

if (HTMLDialogElement.prototype.showModal === undefined) {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute('open', '');
  };
}

if (HTMLDialogElement.prototype.close === undefined) {
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  };
}
