import React from "react";
import { ResponseSensitivityInfo } from "../../api";
import { SensitivityBadge } from "../SensitivityBadge";
import styles from "./ResponseSensitivityBanner.module.css";

interface Props {
    sensitivity: ResponseSensitivityInfo;
}

export const ResponseSensitivityBanner: React.FC<Props> = ({ sensitivity }) => {
    const { overall_label } = sensitivity;
    const finalLabelName = overall_label.display_name?.trim() || overall_label.name?.trim() || "Unknown label";

    return (
        <div className={styles.container}>
            <span className={styles.title}>Response sensitivity label</span>
            <SensitivityBadge label={overall_label} />
            <span className={styles.description}>{`Label name: ${finalLabelName}`}</span>
        </div>
    );
};
