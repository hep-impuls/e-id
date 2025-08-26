document.addEventListener('DOMContentLoaded', () => {
    const fileSelector = document.getElementById('json-file-selector');
    const slidesEditor = document.getElementById('slides-editor');
    const saveButton = document.getElementById('save-button');

    // List of your JSON files
    const jsonFiles = [
        'procontra_1.json',
        'procontra_2.json',
        'procontra_3.json',
        'procontra_4.json',
        'procontra_5.json',
        'test.json',
        'test2.json',
        'test3.json',
        'test4.json'
    ];

    // Populate the file selector dropdown
    jsonFiles.forEach(file => {
        const option = document.createElement('option');
        option.value = file;
        option.textContent = file;
        fileSelector.appendChild(option);
    });

    // Event listener for the file selector
    fileSelector.addEventListener('change', (event) => {
        const fileName = event.target.value;
        if (fileName) {
            loadSlidesForEditing(fileName);
            saveButton.style.display = 'block';
        } else {
            slidesEditor.innerHTML = '';
            saveButton.style.display = 'none';
        }
    });

    // Event listener for the save button
    saveButton.addEventListener('click', () => {
        const fileName = fileSelector.value;
        if (fileName) {
            saveChanges(fileName);
        }
    });

    /**
     * Loads the slides from a JSON file and creates the editor interface.
     * @param {string} fileName - The name of the JSON file to load.
     */
    async function loadSlidesForEditing(fileName) {
        try {
            const response = await fetch(`json/${fileName}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            slidesEditor.innerHTML = ''; // Clear previous slides

            const slides = data.entries || data; // Handle both JSON structures

            slides.forEach((slide, index) => {
                const slideEditor = renderSlideEditor(slide, index, fileName);
                slidesEditor.appendChild(slideEditor);
            });
        } catch (error) {
            console.error("Error loading slides for editing:", error);
            slidesEditor.innerHTML = `<p style="color:red;">Error loading ${fileName}.</p>`;
        }
    }

    /**
     * Renders the editor for a single slide.
     * @param {object} slide - The slide data object.
     * @param {number} index - The index of the slide.
     * @param {string} fileName - The name of the JSON file.
     * @returns {HTMLElement} The slide editor element.
     */
    function renderSlideEditor(slide, index, fileName) {
        const id = fileName.replace('.json', '');
        const imagePath = `images/${id}/${index + 1}.png`;

        const slideContainer = document.createElement('div');
        slideContainer.className = 'slide-editor-card';
        slideContainer.dataset.index = index;

        slideContainer.innerHTML = `
            <h3>Slide ${index + 1}</h3>
            <div class="slide-editor-content">
                <div class="slide-editor-image">
                    <img src="${imagePath}" alt="Image for slide ${index + 1}" onerror="this.style.display='none'; this.parentElement.innerHTML+='<p>Image not found.</p>';">
                </div>
                <div class="slide-editor-text">
                    <label>Concept:</label>
                    <input type="text" class="concept" value="${slide.concept || ''}">
                    <label>Explanation:</label>
                    <textarea class="explanation">${slide.explanation || ''}</textarea>
                    <label>Slide Content:</label>
                    <textarea class="slide_content">${slide.slide_content || ''}</textarea>
                    <label>Timestamp:</label>
                    <input type="text" class="timestamp" value="${slide.timestamp || ''}">
                </div>
            </div>
        `;
        return slideContainer;
    }

    /**
     * Saves the changes to the JSON file.
     * @param {string} fileName - The name of the JSON file to save.
     */
    async function saveChanges(fileName) {
        const slides = [];
        const slideCards = document.querySelectorAll('.slide-editor-card');

        slideCards.forEach(card => {
            const slide = {
                concept: card.querySelector('.concept').value,
                explanation: card.querySelector('.explanation').value,
                slide_content: card.querySelector('.slide_content').value,
                timestamp: card.querySelector('.timestamp').value,
            };
            slides.push(slide);
        });

        // This assumes the original structure had an "entries" key
        const originalStructureHasEntries = (await (await fetch(`json/${fileName}`)).json()).hasOwnProperty('entries');
        const dataToSave = originalStructureHasEntries ? { ...await (await fetch(`json/${fileName}`)).json(), entries: slides } : slides;


        try {
            const response = await fetch('/save-json', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ fileName, data: dataToSave }),
            });

            if (response.ok) {
                alert('Changes saved successfully!');
            } else {
                throw new Error('Failed to save changes.');
            }
        } catch (error) {
            console.error('Error saving changes:', error);
            alert('Error saving changes. See the console for details.');
        }
    }
});